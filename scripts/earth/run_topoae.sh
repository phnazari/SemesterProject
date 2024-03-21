#!/bin/bash

#SBATCH --job-name=earth_topoae
#SBATCH --partition=a40
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=8
#SBATCH --gres=gpu:1
#SBATCH --gres-flags=enforce-binding
#SBATCH --time=30-00:00:00
#SBATCH --output %j.out
#SBATCH --error %j.err

for seed in 1 2 3 4 5
do
python3 source/train.py \
--base_config configs/earth/base_config.yml \
--config configs/earth/topoae.yml \
--logdir results2/earth_z2 \
--run topoae_reg_seed${seed}
done