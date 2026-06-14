from random import  random

ngrain = 8
lx, ly = 100, 200
fdata = open("seed.txt", mode='w+')

fdata.write(f"box {lx} {ly} 0.0\n")
for _ in range(ngrain):
  fdata.write(f"node {random()*lx} {random()*ly} 0.0 0.0 0.0 {(0.5-random())*90}\n")
fdata.close()