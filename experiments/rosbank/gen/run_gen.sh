#!/bin/bash

EPOCHS=10
DEVICE="cuda"
NAME='test'
GENVAL=true

python train_gen_unsupervised.py --total-epochs=$EPOCHS --device=$DEVICE --run-name=$NAME --gen-val=$GENVAL