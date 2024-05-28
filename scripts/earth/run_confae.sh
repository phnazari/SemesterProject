#!/bin/bash

#SBATCH --job-name=earth_confae
#SBATCH --partition=a40
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=8
#SBATCH --gres=gpu:1
#SBATCH --gres-flags=enforce-binding
#SBATCH --time=30-00:00:00
#SBATCH --output %j.out
#SBATCH --error %j.err

for seed in 1 2 3
do
for reg in 0.1 0.01 0.001 0.0001 0.00001 0.000001 0.0000001
do
python source/train.py \
--base_config configs/earth/base_config.yml \
--config configs/earth/confae.yml \
--logdir results2/earth_z2 \
--run confae_reg${reg}_seed${seed} \
--model.conf_reg ${reg} \
--training.seed ${seed} \
--seed $seed \
--device $1
done
done
