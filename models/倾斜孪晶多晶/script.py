from random import  random

ngrain = 12    # 晶粒数量
lx, ly, lz = 200, 200, 200 #盒子大小
theta = 30    # 孪晶角度
fdata = open("seed.txt", mode='w+')

fdata.write(f"box {lx} {ly} {lz}\n")
for _ in range(ngrain):
  fdata.write(f"node {random()*lx} {random()*ly} {random()*lz} 0.0 {(0.5-random())*90} {theta}\n")
fdata.close()