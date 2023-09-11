#!/bin/bash

GPU_ID=1

ALPHA_START_FACTOR=0.1 #Starting number in for loop.
ALPHA_INC_FACTOR=0.1 # Increment factor
MAX_ALPHA=1 #Modify it based on the number of experiments.

MU1_START_FACTOR=0.5  #Starting number in for loop.
MU1_INC_FACTOR=0.5 # Increment factor
MAX_MU1=3 #Modify it based on the number of experiments.

MU2_START_FACTOR=0.5  #Starting number in for loop.
MU2_INC_FACTOR=0.5 # Increment factor
MAX_MU2=3 #Modify it based on the number of experiments.

for alpha in $(seq $ALPHA_START_FACTOR $ALPHA_INC_FACTOR $MAX_ALPHA);
do
  for mu1 in $(seq $MU1_START_FACTOR $MU1_INC_FACTOR $MAX_MU1);
  do
    for mu2 in $(seq $MU2_START_FACTOR $MU2_INC_FACTOR $MAX_MU2);
    do
      CUDA_VISIBLE_DEVICE=$GPU_ID python main.py --dataset PTC --K 205 --alpha "$alpha" --mu1 "$mu1" --mu2 "$mu2"
      CUDA_VISIBLE_DEVICE=$GPU_ID python main.py --dataset IMDBBINARY --K 205 --alpha "$alpha" --mu1 "$mu1" --mu2 "$mu2"
    done
  done
done