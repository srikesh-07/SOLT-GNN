import numpy as np
import torch
from util import load_data


def subgraph_sample(dataset, graph_list, Kl, nums = 500):

    print("Sampling Data")

    with open('dataset/%s/sampling.txt' % (dataset), 'w') as f:
        f.write(str(len(graph_list))+'\n')
        for graph in graph_list:
            border = Kl[int(graph.nodegroup)]
            if graph.nodegroup != 0:
                assert graph.nodegroup < 3
                graph.sample_list = []
                graph.unsample_list = []
                graph.sample_x = []
                n = graph.g.number_of_nodes()
                K = int(min(border-1, n/2))
                f.write(str(K)+'\n')
                graph.K = K
                for i in range(nums):
                    sample_idx = np.random.permutation(n)
                    j = 0
                    sample_set = set()
                    wait_set = []
                    cnt = 0
                    if (len(graph.neighbors[j]) == 0):
                        j += 1
                    wait_set.append(sample_idx[j])
                    while cnt < K:
                        if len(wait_set) != 0:
                            x = wait_set.pop()
                        else:
                            break
                        while x in sample_set:
                            if len(wait_set) != 0:
                                x = wait_set.pop()
                            else:
                                cnt = K
                                break
                        sample_set.add(x)
                        cnt += 1
                        wait_set.extend(graph.neighbors[x])
                    unsample_set = set(range(n)).difference(sample_set)
                    f.write(str(len(sample_set)) + ' ')
                    for x in list(sample_set):
                        f.write(str(x) + ' ')
                    for x in list(unsample_set):
                        f.write(str(x) + ' ')
                    f.write('\n')
            else:
                f.write('0\n')
    print("%s Finished"%(dataset))           

if __name__ == '__main__':

    for dataset in ['PTC', "PROTEINS", "DD", 'FRANK', "IMDBBINARY"]:

        np.random.seed(0)

        graphs, num_classes = load_data(dataset, 0)

        if dataset == 'PTC':
            K = [0, 115, 230, 344]
        elif dataset == "PROTEINS":
            K = [0, 371, 742, 1113]
        elif dataset == "IMDBBINARY":
            K = [0, 333, 666, 1000]
        elif dataset == "DD":
            K = [0, 393, 785, 1178]
        elif dataset == "FRANK":
            K = [0, 1445, 2890, 4337]

        nodes = torch.zeros(len(graphs))

        for i in range(len(graphs)):
            nodes[i] = graphs[i].g.number_of_nodes()

        _, ind = torch.sort(nodes, descending=True)

        for i in ind[K[0]:K[1]]:
            graphs[i].nodegroup = 2
        for i in ind[K[1]:K[2]]:
            graphs[i].nodegroup = 1
        for i in ind[K[2]:K[3]]:
            graphs[i].nodegroup = 0

        subgraph_sample(dataset, graphs, K)
