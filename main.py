import argparse
import random
import os

os.environ["CUDA_DEVICE_ORDER"]="PCI_BUS_ID"

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from numpy.core.numeric import False_

from gin import GIN
from PatternMemory import PatternMemory
from util import data_split, load_data, load_sample

criterion_ce = nn.CrossEntropyLoss()
criterion_cs = nn.CosineSimilarity(dim=1, eps=1e-7)

def train_gin(args, model, device, graphs, optimizer, epoch):
    model.train()
    print('epoch: %d' % (epoch), end=" ")
    loss_accum = 0
    minibatch_size = args.batch_size
    idx = np.arange(len(graphs))
    shuffle_idx = np.random.permutation(len(graphs))
    train_graphs = [graphs[id] for id in shuffle_idx]
    for i in range(0, len(train_graphs), minibatch_size):
        selected_idx = idx[i:i+minibatch_size]
        if len(selected_idx) == 0:
            continue
        batch_graph_h = [train_graphs[idx] for idx in selected_idx]
        output_h = model(batch_graph_h)
        labels_h = torch.LongTensor([graph.label for graph in batch_graph_h]).to(device)
        loss = criterion_ce(output_h, labels_h)
        if optimizer is not None:
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        loss = loss.detach().cpu().numpy()
        loss_accum += loss
    average_loss = loss_accum/float(len(train_graphs))
    print("loss training: %f" % (average_loss), end = ' ')
    return average_loss

@torch.no_grad()
def pass_data_iteratively_gin(model, graphs, minibatch_size = 128):
    model.eval()
    output = []
    idx = np.arange(len(graphs))
    for i in range(0, len(graphs), minibatch_size):
        sampled_idx = idx[i:i+minibatch_size]
        if len(sampled_idx) == 0:
            continue
        output.append(model([graphs[j] for j in sampled_idx]).detach())
    return torch.cat(output, 0)


@torch.no_grad()
def test_gin(args, model, device, graphs, epoch):
    model.eval()
    output = pass_data_iteratively_gin(model, graphs)
    pred = output.max(1, keepdim=True)[1]
    labels = torch.LongTensor(
        [graph.label for graph in graphs]).to(device)
    loss =  criterion_ce(output, labels)
    correct = pred.eq(labels.view_as(
        pred)).sum().cpu().item()
    acc = correct / len(graphs)
    mask_h = torch.zeros(len(graphs))
    for j in range(len(graphs)):
        mask_h[j] = graphs[j].nodegroup
    mask_h = mask_h.bool()
    correct = pred[mask_h].eq(labels[mask_h].view_as(
        pred[mask_h])).sum().cpu().item()

    return loss, acc, correct


def train(args, model, patmem, device, graphs, samples, optimizer, optimizer_p, epoch):
    model.train()
    patmem.train()
    minibatch_size = args.batch_size
    loss_accum = 0
    print('epoch: %d' % (epoch+1), end=" ")

    shuffle = np.random.permutation(len(graphs))
    train_graphs = [graphs[ind] for ind in shuffle]
    train_samples = [samples[ind] for ind in shuffle]

    idx = np.arange(len(train_graphs))

    l_h = l_t = l_n = l_g = l_d = 0

    for i in range(0, len(train_graphs), minibatch_size):

        selected_idx = idx[i:i+minibatch_size]

        if len(selected_idx) == 0:
            continue

        batch_graph_h = [train_graphs[idx]
                         for idx in selected_idx if train_graphs[idx].nodegroup == 2]
        batch_samples_h = [train_samples[idx]
                           for idx in selected_idx if train_graphs[idx].nodegroup == 2]
        batch_graph_t = [train_graphs[idx]
                         for idx in selected_idx if train_graphs[idx].nodegroup == 0]

        n_h = len(batch_graph_h)
        n_t = len(batch_graph_t)
        n = n_h + n_t

        if n_h <= 1 or n_t == 0:
            continue

        embeddings_head = model.get_patterns(batch_graph_h)

        gsize = np.zeros(n_h+1, dtype=int)

        for i, graph in enumerate(batch_graph_h):
            gsize[i+1] = gsize[i] + graph.g.number_of_nodes()

        q_idx = []
        pos_idx = []
        neg_idx = []
        pos_rep = []
        neg_rep = []

        for i, graph in enumerate(batch_graph_h):
            graph.sample_list = batch_samples_h[i].sample_list[epoch]
            gsize[i+1] = gsize[i] + graph.g.number_of_nodes()
            uidx = batch_samples_h[i].unsample_list[epoch] + gsize[i]
            pos_rep.append(embeddings_head[uidx].sum(dim=0, keepdim=True))
            for _ in range(args.n_g):
                neg = np.random.randint(n_h)
                while (neg == i):
                    neg = np.random.randint(n_h)
                m = min(len(uidx), batch_graph_h[neg].g.number_of_nodes())
                sample_idx = torch.tensor(np.random.permutation(
                    batch_graph_h[neg].g.number_of_nodes())).long()
                sample_idx += gsize[neg]
                neg_rep.append(embeddings_head[sample_idx[:m]].sum(dim=0, keepdim=True))
            for _ in range(args.n_n):
                neg = np.random.randint(n_h)
                while (neg == i):
                    neg = np.random.randint(n_h)
                size = min(batch_graph_h[neg].g.number_of_nodes(
                ), batch_graph_h[i].g.number_of_nodes())
                q_idx.append(torch.arange(gsize[i], gsize[i]+size).long())
                sample_idx = torch.tensor(np.random.permutation(
                    graph.g.number_of_nodes())).long()
                sample_idx += gsize[i]
                pos_idx.append(sample_idx[:size])
                sample_idx = torch.tensor(np.random.permutation(
                    batch_graph_h[neg].g.number_of_nodes())).long()
                sample_idx += gsize[neg]
                neg_idx.append(sample_idx[:size])

        q_idx = torch.cat(q_idx).long()
        pos_idx = torch.cat(pos_idx).long()
        neg_idx = torch.cat(neg_idx).long()

        query = patmem(embeddings_head[q_idx])
        pos = embeddings_head[pos_idx]
        neg = embeddings_head[neg_idx]

        
        loss_n = - (torch.mul(query.div(torch.norm(query, dim=1).reshape(-1, 1)+1e-7), pos.div(torch.norm(pos, dim=1).reshape(-1, 1)+1e-7)).sum(dim=1) -
                    torch.mul(query.div(torch.norm(query, dim=1).reshape(-1, 1)+1e-7), neg.div(torch.norm(neg, dim=1).reshape(-1, 1)+1e-7)).sum(dim=1)).sigmoid().log().mean()

        subgraph_rep = model.subgraph_rep(batch_graph_h)
        pos_rep = torch.cat(pos_rep)
        neg_rep = torch.cat(neg_rep)
        query_g = patmem(subgraph_rep).repeat(args.n_g,1)
        pos_g = pos_rep.repeat(args.n_g,1)
        neg_g = neg_rep

        loss_g = - (torch.mul(query_g.div(torch.norm(query_g, dim=1).reshape(-1, 1)+1e-7), pos_g.div(torch.norm(pos_g, dim=1).reshape(-1, 1)+1e-7)).sum(dim=1) -
                    torch.mul(query_g.div(torch.norm(query_g, dim=1).reshape(-1, 1)+1e-7), neg_g.div(torch.norm(neg_g, dim=1).reshape(-1, 1)+1e-7)).sum(dim=1)).sigmoid().log().mean()
        

        graph_repre_head = model.get_graph_repre(batch_graph_h)
        patterns_head = patmem(graph_repre_head)
        output_h = model.predict(graph_repre_head + patterns_head)
        labels_h = torch.LongTensor([graph.label for graph in batch_graph_h]).to(device)
        loss_h = criterion_ce(output_h, labels_h)

        graph_repre_tail = model.get_graph_repre(batch_graph_t)
        patterns_tail = patmem(graph_repre_tail)
        output_t = model.predict(graph_repre_tail + patterns_tail)
        labels_t = torch.LongTensor([graph.label for graph in batch_graph_t]).to(device)
        loss_t = criterion_ce(output_t, labels_t)

        loss_d = (criterion_cs(graph_repre_tail, patterns_tail).sum() + criterion_cs(graph_repre_head, patterns_head).sum()) / n

        l_t += loss_t.detach().cpu().numpy()
        l_h += loss_h.detach().cpu().numpy()
        l_n += loss_n.detach().cpu().numpy()
        l_g += loss_g.detach().cpu().numpy()
        l_d += loss_d.detach().cpu().numpy()

        loss = 2 * (args.alpha * loss_h +  (1-args.alpha) * loss_t) + args.mu1 * loss_n + args.mu2 * loss_g + args.lbd * loss_d

        optimizer.zero_grad()
        optimizer_p.zero_grad()
        loss.backward()
        optimizer.step()
        optimizer_p.step()

        loss = loss.detach().cpu().numpy()
        loss_accum += loss


    print("Loss Training: %f Head: %f Tail: %f Node: %f Graph: %f Dis: %f" %
          (loss_accum, l_t, l_h,  l_n, l_g, l_d))

    return loss_accum

@torch.no_grad()
def pass_data_iteratively(args, model, patmem, graphs, device, minibatch_size=128):
    model.eval()
    patmem.eval()
    output = []
    labels = []
    idx = np.arange(len(graphs))
    for i in range(0, len(graphs), minibatch_size):
        selected_idx = idx[i:i+minibatch_size]
        if len(selected_idx) == 0:
            continue
        batch_graph = [graphs[i] for i in selected_idx]

        embeddings_graph = model.get_graph_repre(batch_graph)
        patterns = patmem(embeddings_graph)

        output.append(model.predict(embeddings_graph + patterns))
        labels.append(torch.LongTensor([graph.label for graph in batch_graph]))

    return torch.cat(output, 0), torch.cat(labels, 0).to(device)


@torch.no_grad()
def test(args, model, patmem, device, graphs, epoch):
    model.eval()
    output, labels = pass_data_iteratively(
        args, model, patmem, graphs, device)
    pred = output.max(1, keepdim=True)[1]
    labels = torch.LongTensor(
        [graph.label for graph in graphs]).to(device)
    loss_all = criterion_ce(output, labels)
    correct_all = pred.eq(labels.view_as(
        pred)).sum().cpu().item()
    acc_all = correct_all / len(graphs)
    mask = torch.zeros(len(graphs))
    for j in range(len(graphs)):
        mask[j] = graphs[j].nodegroup
    mask_head = (mask == 2)
    mask_medium = (mask == 1)
    mask_tail = (mask == 0)
    loss_head = criterion_ce(output[mask_head], labels[mask_head])
    correct_head = pred[mask_head].eq(labels[mask_head].view_as(
        pred[mask_head])).sum().cpu().item()
    acc_head = correct_head / float(mask_head.sum())
    loss_medium = criterion_ce(output[mask_medium], labels[mask_medium])
    correct_medium = pred[mask_medium].eq(labels[mask_medium].view_as(
        pred[mask_medium])).sum().cpu().item()
    acc_medium = correct_medium / float(mask_medium.sum())
    loss_tail = criterion_ce(output[mask_tail], labels[mask_tail])
    correct_tail = pred[mask_tail].eq(labels[mask_tail].view_as(
        pred[mask_tail])).sum().cpu().item()
    acc_tail = correct_tail / float(mask_tail.sum())

    return loss_all, acc_all, acc_head, acc_medium, acc_tail


def main():
    # Note: Hyper-parameters need to be tuned in order to obtain results reported in the paper.
    parser = argparse.ArgumentParser(
        description='PyTorch graph convolutional neural net for whole-graph classification')
    parser.add_argument('--dataset', type=str, default="PTC",
                        help='name of dataset (default: PTC)')
    parser.add_argument('--device', type=int, default=0,
                        help='which g pu to use if any (default: 0)')
    parser.add_argument('--batch_size', type=int, default=32,
                        help='input batch size for training (default: 32)')
    parser.add_argument('--epochs', type=int, default=500,
                        help='number of epochs to train (default: 500)')
    parser.add_argument('--lr', type=float, default=0.01,
                        help='learning rate (default: 0.01)')
    parser.add_argument('--seed', type=int, default=0,
                        help='random seed for splitting the dataset')
    parser.add_argument('--test_ratio', type=float, default=0.2,
                        help='test data ratio')
    parser.add_argument('--valid_ratio', type=float, default=0.1,
                        help='valid data ratio')
    parser.add_argument('--num_layers', type=int, default=5,
                        help='number of layers INCLUDING the input one (default: 5)')
    parser.add_argument('--num_mlp_layers', type=int, default=2,
                        help='number of layers for MLP EXCLUDING the input one (default: 2). 1 means linear model.')
    parser.add_argument('--hidden_dim', type=int, default=32,
                        help='number of hidden units (default: 32)')
    parser.add_argument('--dropout', type=float, default=0.5,
                        help='final layer dropout (default: 0.5)')
    parser.add_argument('--graph_pooling_type', type=str, default="sum", choices=["sum", "average"],
                        help='Pooling for over nodes in a graph: sum or average')
    parser.add_argument('--neighbor_pooling_type', type=str, default="sum", choices=["sum", "average", "max"],
                        help='Pooling for over neighboring nodes: sum, average or max')
    parser.add_argument('--learn_eps', action="store_true",
                        help='Whether to learn the epsilon weighting for the center nodes. Does not affect training accuracy though.')
    parser.add_argument('--degree_as_tag', action="store_true",
                        help='let the input node features be the degree of nodes (heuristics for unlabeled graph)')
    parser.add_argument('--l2', type=float, default=5e-4,
                        help='the weight decay of adam optimizer')
    parser.add_argument('--alpha', type=float, default=0.5,
                        help=r'weight of head graph classification loss($\alpha $ in the paper)')
    parser.add_argument('--mu1', type=float, default=1.0,
                        help='weight of node-level co-occurrence loss($\mu_1$ in the paper)')
    parser.add_argument('--mu2', type=float, default=1.0,
                        help='weight of subgraph-level co-occurrence loss($\mu_2$ in the paper)')
    parser.add_argument('--lbd', type=float, default=1e-4,
                        help='weight of dissimilarity regularization loss($\lambda $ in the paper)')
    parser.add_argument('--dm', type=int, default=64,
                        help='dimension of pattern memory($d_m $ in the paper)')
    parser.add_argument('--K', type=int, default=72,
                        help='the number of head graphs($K $ in the paper)')
    parser.add_argument('--n_n', type=int, default=1,
                        help='the number of node-level co-occurrence triplets per node at single epoch')
    parser.add_argument('--n_g', type=int, default=1,
                        help='the number of subgraph-level co-occurrence triplets per graph at single epoch')
    args = parser.parse_args()

    degree_state = 0
    seed = 0

    #Base Hyper-parameter configuration
    if args.dataset == "PROTEINS":
        hidden_dim = 32
        batch_size = 32
        seed = 2022
        learn_eps = False
        l2 = 0
        K = [0, 371, 742, 1113]
    elif args.dataset == "PTC": 
        hidden_dim = 32
        batch_size = 32
        seed = 0
        learn_eps = True
        l2 = 5e-4
        K = [0, 115, 230, 344]
    elif args.dataset == "IMDBBINARY": 
        hidden_dim = 64
        batch_size = 32
        seed = 2020
        learn_eps = True
        l2 = 5e-4
        K = [0, 333, 666, 1000]
    elif args.dataset == "DD":
        hidden_dim = 32
        batch_size = 128
        seed = 2022
        learn_eps = False
        l2 = 0
        K = [0, 393, 785, 1178]
    elif args.dataset == "FRANK":
        hidden_dim = 32
        batch_size = 128
        learn_eps = True
        l2 = 5e-4
        K =[0, 1445, 2890, 4337]

    args.hidden_dim = hidden_dim
    args.batch_size = batch_size
    args.l2 = l2
    args.learn_eps = learn_eps
    args.seed = seed

    graphs, num_classes = load_data(args.dataset, degree_state)

    gsamples = load_sample(args.dataset)
    print(gsamples)

    nodes = torch.zeros(len(graphs))
    print(nodes.shape)

    for i in range(len(graphs)):
        nodes[i] = graphs[i].g.number_of_nodes()
        
    _, ind = torch.sort(nodes, descending=True)

    for i in ind[K[0]:K[1]]:
        graphs[i].nodegroup = 2
    for i in ind[K[1]:K[2]]:
        graphs[i].nodegroup = 1
    for i in ind[K[2]:K[3]]:
        graphs[i].nodegroup = 0

    train_graphs, valid_graphs, test_graphs, train_samples = data_split(graphs, gsamples, args.valid_ratio, args.test_ratio, args.seed)
    print(len(train_graphs), len(valid_graphs), len(test_graphs), len(train_samples))

    cnt_node = torch.zeros(3)

    for i in range(len(test_graphs)):
        cnt_node[test_graphs[i].nodegroup] += 1

    print('The number of graphs in test set:', end=' ')
    print("Head: %f" % (cnt_node[2]), end=', ')
    print("Medium: %f" % (cnt_node[1]), end=', ')
    print("Tail: %f" % (cnt_node[0]))

    times = 5

    test_record = torch.zeros(times)
    valid_record = torch.zeros(times)
    tail_record = torch.zeros(times)
    medium_record = torch.zeros(times)
    head_record = torch.zeros(times)
    
    for seed in range(times):

        random.seed(seed)
        torch.manual_seed(seed)
        np.random.seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)
            torch.backends.cudnn.deterministic = True  
        
        device = torch.device("cuda:" + str(args.device)
                            ) if torch.cuda.is_available() else torch.device("cpu")

        print("Train GIN firstly for head graphs")

        model = GIN(args.num_layers, args.num_mlp_layers, train_graphs[0].node_features.shape[1], args.hidden_dim, num_classes, args.dropout, args.learn_eps, args.graph_pooling_type, args.neighbor_pooling_type, device).to(device)

        optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.l2)

        scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=50, gamma=0.5)

        test_acc = 0
        best_valid_acc = 0
        best_valid_loss = 100000
        correct = 0
        patience = 0

        for epoch in range(0, args.epochs):
            scheduler.step()

            _ = train_gin(args, model, device, train_graphs, optimizer,  epoch)

            loss_valid, acc_valid, _ = test_gin(args, model, device, valid_graphs, epoch)

            print("valid loss: %.4f acc: %.4f" % (loss_valid, acc_valid))

            if loss_valid < best_valid_loss and acc_valid > best_valid_acc:
                _, temp_acc, tenp_correct = test_gin(args, model, device, test_graphs, epoch)
                best_valid_acc = acc_valid
                best_valid_loss = loss_valid
                patience = 0
                if temp_acc > test_acc:
                    print("test acc: %.4f" % test_acc)
                    test_acc = temp_acc
                    correct = temp_correct
            else:
                patience += 1
            
            if patience == 100:
                break

        print("Train SOLTGIN for tail graphs")

        model = GIN(args.num_layers, args.num_mlp_layers, train_graphs[0].node_features.shape[1], args.hidden_dim, num_classes,
                    args.dropout, args.learn_eps, args.graph_pooling_type, args.neighbor_pooling_type, device).to(device)
        patmem = PatternMemory(args.hidden_dim, args.dm).to(device)

        optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.l2)

        scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=50, gamma=0.5)

        opt_p = optim.Adam(patmem.parameters(), lr=args.lr, weight_decay=args.l2)

        test_acc = 0
        best_valid_acc = 0
        best_valid_loss = 100000
        best_test_acc = 0
        best_test_head=0
        best_test_med=0
        best_test_tail=0
        patience = 0
        # test_acc_list= []
        # test_acc_head_list = []
        # test_acc_medium_list = []
        # test_acc_tail_list = []

        for epoch in range(0, args.epochs):
            scheduler.step()

            _ = train(args, model, patmem, device, train_graphs, train_samples, optimizer, opt_p, epoch)

            loss_valid, acc_valid, acc_head_valid, acc_medium_valid, acc_tail_valid= test(args, model, patmem, device, valid_graphs, epoch)

            print("valid loss: %.4f acc: %.4f" % (loss_valid, acc_valid))

            if loss_valid < best_valid_loss and acc_valid > best_valid_acc:
                best_valid_acc = acc_valid
                best_valid_loss = loss_valid
                loss, test_acc, test_acc_head, test_acc_medium, test_acc_tail = test(args, model, patmem, device, test_graphs, epoch)
                print("test acc: %.4f" % test_acc)
                print("test acc_head: %.4f" % test_acc_head)
                print("test acc_medium: %.4f" % test_acc_medium)
                print("test acc_tail: %.4f" % test_acc_tail)
                if test_acc > best_test_acc:
                    best_test_acc = test_acc
                    best_test_head = test_acc_head
                    best_test_med = test_acc_medium
                    best_test_tail = test_acc_tail
                # test_acc_list.append(test_acc)
                # test_acc_head_list.append(test_acc_head)
                # test_acc_medium_list.append(test_acc_medium)
                # test_acc_tail_list.append(test_acc_tail)
                patience = 0
                # _, tail_acc, correct_tail = test(args, model, patmem, device, test_graphs, epoch)
            else:
                patience += 1
            
            if patience == 100:
                break

        print("Seed: %.4f valid acc: %.4f test acc: %.4f tail acc: %.4f" % (seed, best_valid_acc, test_acc, test_acc_tail))

        test_record[seed] =  test_acc
        valid_record[seed] = best_test_acc
        head_record[seed] = best_test_head
        medium_record[seed] = best_test_med
        tail_record[seed] = best_test_tail


    print('Valid mean: %.4f, std: %.4f' %
          (valid_record.mean().item(), valid_record.std().item()))
    print('Test mean: %.4f, std: %.4f' %
          (test_record.mean().item(), test_record.std().item()))
    print('Head mean: %.4f, std: %.4f' %
          (head_record.mean().item(), head_record.std().item()))
    print('Medium mean: %.4f, std: %.4f' %
          (medium_record.mean().item(), medium_record.std().item()))
    print('Tail mean: %.4f, std: %.4f' %
          (tail_record.mean().item(), tail_record.std().item()))

    with open("metrics.txt", "a") as txt_file:
        txt_file.write(f"Dataset: {args.dataset}, \n"
                       f"Valid Mean: {round(valid_record.mean().item(), 4)}, \n"
                       f"Std Valid Mean: {round(valid_record.std().item(), 4)}, \n"
                       f"Test Mean: {round(test_record.mean().item(), 4)}, \n"
                       f"Std Test Mean: {round(test_record.std().item(), 4)}, \n"
                       f"Head Mean: {round(head_record.mean().item(), 4)}, \n"
                       f"Std Head Mean: {round(head_record.std().item(), 4)}, \n"
                       f"Medium Mean: {round(medium_record.mean().item(), 4)}, \n"
                       f"Std Medium Mean: {round(medium_record.std().item(), 4)}, \n"
                       f"Tail Mean: {round(tail_record.mean().item(), 4)}, \n"
                       f"Std Tail Mean: {round(tail_record.std().item(), 4)} \n\n"
        )

if __name__ == '__main__':
    main()
