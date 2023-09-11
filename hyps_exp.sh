#!/bin/bash

GPU_ID=0
DATASET="IMDBBINARY"

ALPHA_START_FACTOR=0.1 #Starting number in for loop.
ALPHA_INC_FACTOR=0.1 # Increment factor
MAX_ALPHA=1 #Modify it based on the number of experiments.


MU_START_FACTOR=0.5  #Starting number in for loop.
MU_INC_FACTOR=0.5 # Increment factor
MAX_MU=1 #Modify it based on the number of experiments.

for alpha in $(seq $ALPHA_START_FACTOR $ALPHA_INC_FACTOR $MAX_ALPHA);
do
  for mu in $(seq $MU_START_FACTOR $MU_INC_FACTOR $MAX_MU);
  do
      CUDA_VISIBLE_DEVICE=$GPU_ID python main.py --dataset $DATASET --K 205 --alpha "$alpha" --mu1 "$mu" --mu2 "$mu"
  done
done