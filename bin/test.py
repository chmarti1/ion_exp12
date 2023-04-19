#!/usr/bin/python3

import os,sys
import time

data_dir = '../data'

target = os.path.join(data_dir, time.strftime('%Y%m%d%H%M%S'))
prefile = os.path.join(target, '_pre.dat')
postfile = os.path.join(target, '_post.dat')

# Make the target directory
os.mkdir(target)

target = os.path.join(target, 'wscan')

# Prompt the user for input
go_f = True
while go_f:
    zinit_mm = float(input('Initial z (mm):'))
    print('Are the above entries correct?')
    go_f = not (input('(Y/n):') == 'Y')

# Run the flow measurement
print('Pre-flow measurement')
os.system('lcburst -c flow.conf -d ' + prefile)

# Run the measurement
print('Measuring...')
os.system(f'./wscan -c wscan.conf -d {target} -f zinit_mm={zinit_mm}')

# Run the flow measurement
print('Post-flow measurement')
os.system('lcburst -c flow.conf -d ' + postfile)
