# -*- coding: utf-8 -*-
"""Train & VALIDATION.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1t4WuuV-DMZiTiPjMofIRPSPYRZ1l5W65



"""# **🐮 Libraries**"""
import os

# Commented out IPython magic to ensure Python compatibility.
# %%time
# 
os.system('pip install --upgrade albumentations -qqq')
os.system('pip install timm -qqq')

import cv2
import sys
from tqdm import tqdm
import random
import easydict

import pandas as pd
from glob import glob
import numpy as np
from pathlib import Path
from datetime import datetime
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings("ignore")

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

import timm
import albumentations as A
from albumentations.pytorch import ToTensorV2

"""# **🥽 Configuration**"""

from albumentations.augmentations.geometric.resize import Resize
device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
root_path = '/content/drive/MyDrive/DACON/Image_Classification/Landmark/'

args = easydict.EasyDict({ # EasyDict 는 속성으로 dict 값에 액세스 할 수 있습니다.(재귀적으로 작동). 
    'image_path' : root_path + 'data/train/',
    'label_path' : root_path + 'data/train.csv',
    'kfold_idx' : 1 , # 0~4까지 바꿔가면서 5번 학습

    'epochs' : 20,
    'batch_size' : 32,
    'lr' : 1e-3,
    'patience' : 8,
    'seed' : 777,
    'worker' : torch.cuda.device_count() * 4,
    'model' : 'resnet50',
    'pretrained' : False,

    'resume' : None,
    'device' : device,
    'comments': None,




    # augmentation
    'train_aug' : A.Compose([
                         A.Resize(224, 224),
                         A.VerticalFlip(p = 0.2),
                         A.HorizontalFlip(p=0.2),
                         A.ShiftScaleRotate(shift_limit=0.1, 
                           scale_limit=0.15, 
                           rotate_limit=60, 
                           p=0.5),
                        #  A.HueSaturationValue(
                                # hue_shift_limit=0.2, 
                                # sat_shift_limit=0/.2, 
                                # val_shift_limit=0.2, 
                                # p=0.5
                            # ),
                         A.RandomBrightnessContrast(
                                brightness_limit=(-0.1,0.1), 
                                contrast_limit=(-0.1, 0.1), 
                                p=0.5
                            ),
                         A.Normalize(max_pixel_value=1.0, p=1),
                         ToTensorV2() # h,w,c -> c,h,w
  ]),
    'val_aug' : A.Compose([
                        A.Resize(224,224),
                        A.Normalize(max_pixel_value=1.0, p=1),
                        ToTensorV2()
    ]),

    'test_aug' : A.Compose([
                         A.Resize(224,224),
                        #  A.VerticalFlip(p=0.5),
                        #  A.HorizontalFlip(p=0.5),
                        # A.Resize(224,224),
                        A.Normalize(max_pixel_value=1.0, p=1),
                        ToTensorV2()
  ])
})

def seed_everything(seed):
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = True

seed_everything(args.seed)

#GPU 체크 및 할당
if torch.cuda.is_available():    
    #device = torch.device("cuda:0")
    print('Device:', device)
    print('There are %d GPU(s) available.' % torch.cuda.device_count())
    print('We will use the GPU:', torch.cuda.get_device_name(0))
else:
    device = torch.device("cpu")
    print('No GPU available, using the CPU instead.')

"""# **🍿 Data Preprocessing**

### **CustomDataset**
"""

class DatasetLM(Dataset):
    def __init__(self, image_folder, label_df, transforms):
        self.image_folder = image_folder
        self.label_df = label_df
        self.transforms = transforms

    def __len__(self):
        return len(self.label_df)

    def __getitem__(self, index):
        image_fn = self.image_folder + str(self.label_df.iloc[index,0])

        image = cv2.imread(image_fn)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


        label = self.label_df.iloc[index,1]

        if self.transforms:
            image = self.transforms(image=image)['image']
        
        return image, label


"""# **🧦 Train & Validation**"""

# train

def train(train_loader, model, loss_func, device, optimizer, scheduler=None):
    n = 0
    running_loss = 0.0
    running_corrects = 0

    epoch_loss = 0.0
    epoch_acc = 0.0

    model.train()

    # sys.stdout : 보통 프로그램 수행 과정에서 몇 시에 어떤 작업을 어떤 식으로 수행하고 있으며 그 결과는 어떠한지 등의 정보를 가지는 로그를 남길 때 stdout 은 일반적인 내용을, stderr 는 에러 발생 시 관련 내용을 출력하기 위해 사용할 수 있습니다.
    with tqdm(train_loader, total=len(train_loader), desc='Train', file=sys.stdout) as iterator:
        
        for train_x, train_y in iterator:
            train_x, train_y = train_x.to(device), train_y.to(device)

            output = model(train_x)
            _, preds = torch.max(output,1)

            loss = loss_func(output, train_y)

            n += train_x.size(0)
            running_loss += loss.item() * train_x.size(0)
            running_corrects += (preds==train_y).sum().item()

            
            epoch_acc = running_corrects /  n
            epoch_loss = running_loss / n

            log = f"Train_loss - {epoch_loss:.5f}, Train_acc - {epoch_acc:.5f}"

            iterator.set_postfix_str(log)

            optimizer.zero_grad() #배치마다 optimizer 초기화
            loss.backward() #손실함수 기준 역전파 
            torch.nn.utils.clip_grad_norm(model.parameters(),1) # Clips gradient norm of an iterable of parameters.
            optimizer.step() #가중치 최적화
        
    if scheduler:
        scheduler.step(epoch_loss)
    
    return epoch_loss, epoch_acc


def validate(valid_loader, model, loss_func, device, scheduler=None):

    n = 0
    running_loss = 0.0
    running_corrects = 0

    epoch_loss = 0.0
    epoch_acc = 0.0

    model.eval()

    with tqdm(valid_loader, total=len(valid_loader), desc='Valid', file=sys.stdout) as iterator:
        for x,y in iterator:
            x,y = x.to(device), y.to(device)

            with torch.no_grad():
                output = model(x)

            loss = loss_func(output,y)

            n += x.size(0)
            running_loss += loss.item() * x.size(0)

            epoch_loss = running_loss / n

            _, preds = torch.max(output,1)
            running_corrects += (preds==y).sum().item()
            epoch_acc = running_corrects / n

            log = f"Val_loss - {epoch_loss:.5f}, Val_acc - {epoch_acc:.5f}"

            iterator.set_postfix_str(log)
    if scheduler:
        scheduler.step(epoch_loss)

    return epoch_loss, epoch_acc

# checkin args
print('=' * 75)
print('[info msg] arguments\n')
for key, value in vars(args).items(): # 객체의 __dict__ 속성 반환
    print(key, ' : ', value)
print('\n','=' * 75)

assert os.path.isdir(args.image_path), 'wrong path'
assert os.path.isfile(args.label_path), 'wrong path'
if (args.resume):
    assert os.path.isfile(args.resume), 'wrong path'
assert args.kfold_idx < 5


# Data Split for Fold & DataLoader Generation
data_set = pd.read_csv(args.label_path)
valid_idx_nb = int(len(data_set) * (1/5)) # int(723/5)
valid_idx = np.arange(valid_idx_nb * args.kfold_idx, valid_idx_nb * (args.kfold_idx + 1))

print('[info msg] validation fold idx !!\n')        
print(valid_idx)
print('=' * 75)

train_data = data_set.drop(valid_idx) # valid_idx에 해당되는 데이터를 제거하고 남은 데이터들
valid_data = data_set.iloc[valid_idx] # valid_idx에 포함되는 데이터들

train_set = DatasetLM(
    image_folder = args.image_path,
    label_df = train_data,
    transforms=args.train_aug
)


valid_set = DatasetLM(
    image_folder = args.image_path,
    label_df = valid_data,
    transforms = args.val_aug
)

train_data_loader = DataLoader(
    train_set,
    batch_size = args.batch_size,
    shuffle=True)

valid_data_loader = DataLoader(
    valid_set,
    batch_size = args.batch_size,
    shuffle=False
)

model = None


if(args.resume):
    model = timm.create_model(args.model, checkpoint_path=args.resume, num_classes=10, drop_rate=0.3)
    print('[info msg] pre-trained weight is loaded !! ')
    print('[Info msg] Resume Training will be started')
    print(f'[Info msg] Pretrained_weight path \n ------> {args.resume}\n\n')
    print('=' * 70)
else:
    print(f'[info msg] {args.model} model with (pretrained : {args.pretrained}) is created\n')
    model = timm.create_model(args.model, pretrained=args.pretrained, num_classes=10,\
                          drop_rate=0.3)
    print('=' * 70)

if args.device == 'cuda:0' and torch.cuda.device_count() > 1 :
    model = torch.nn.DataParallel(model)

model.to(args.device)

optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
criterion = torch.nn.CrossEntropyLoss() # softmax automatically
scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
    optimizer = optimizer,
    mode='min',
    patience=2,
    factor=0.3,
    verbose=True
)


train_loss = []
train_acc = []
valid_loss = []
valid_acc = []

best_loss = float('inf')

patience = 0

date_time = datetime.now().strftime('%m%d%H%M%S')
if not os.path.exists('./save'):
    os.mkdir('./save')
SAVE_DIR = os.path.join('./save', date_time)

print('[info msg] TRAINING START !!!!')
print(f'[Info msg] kfold_idx is {args.kfold_idx} \n')
startTime = datetime.now()

for epoch in range(args.epochs):
    print(f"Epoch {epoch+1}/{args.epochs}")
    train_epoch_loss, train_epoch_acc = train(
        train_loader = train_data_loader,
        model=model,
        loss_func = criterion,
        device=args.device,
        optimizer=optimizer,
    )
    # list appending
    train_loss.append(train_epoch_loss)
    train_acc.append(train_epoch_acc)

    valid_epoch_loss, valid_epoch_acc = validate(
        valid_loader = valid_data_loader,
        model=model,
        loss_func=criterion,
        device=args.device,
        scheduler=scheduler,
    )
    # list appending
    valid_loss.append(valid_epoch_loss)
    valid_acc.append(valid_epoch_acc)


    # Save Best Model
    if best_loss > valid_epoch_loss:
        patience = 0
        best_loss = valid_epoch_loss

        Path(SAVE_DIR).mkdir(parents=True, exist_ok=True)
        torch.save(model.state_dict(), os.path.join(SAVE_DIR,'model_best.pth'))
        print(f"MODEL IS SAVED TO {date_time}!!!!")

    else :
        patience += 1
        if patience > args.patience -1:
            print("=========" * 10)
            print('[Info message] Early Stopper is activated')
            break

elapsed_time = datetime.now() - startTime

train_loss = np.array(train_loss)
train_acc = np.array(train_acc)
valid_loss = np.array(valid_loss)
valid_acc = np.array(valid_acc)

best_loss_pos = np.argmin(valid_loss) # index 출력


print('=' * 70)
print('[info msg] TRAINING is DONE\n')
print(f"Time taken: {elapsed_time}.")
print(f"best loss is {best_loss:.5f} w/ acc {valid_acc[best_loss_pos]:.5f} at epoch : {best_loss_pos}.")    

print('=' * 70)
print(f'[info msg] {args.model} model weight and log are saved to {SAVE_DIR}\n')

# Save Log
with open(os.path.join(SAVE_DIR, 'log.txt'),'w') as f:
    for key, value in vars(args).items():
        f.write(f"{key} : {value}\n")

    f.write('\n')
    f.write(f"Total Epochs : {str(train_loss.shape[0])}\n")
    f.write(f"Time Taken : {str(elapsed_time)}")
    f.write(f"Best_Train_Loss {np.min(train_loss)} w/acc {np.argmin(train_loss)} at epoch : {np.argmin(train_loss)}")
    f.write(f'Best_Valid_Loss {np.min(valid_loss)} w/ acc {valid_acc[np.argmin(valid_loss)]} at epoch : {np.argmin(valid_loss)}')

plt.figure(figsize=(15,5))
plt.subplot(1,2,1) # nrows, ncols, index
plt.plot(train_loss, label='train_loss')
plt.plot(valid_loss,'o',label='valid_loss')
plt.axvline(x=best_loss_pos, color='r', linestyle='--', linewidth=1.5)
plt.legend()

plt.subplot(1,2,2)
plt.plot(train_acc, label='train_acc')
plt.plot(valid_acc, 'o', label='valid_acc')
plt.axvline(x=best_loss_pos, color='r', linestyle='--', linewidth=1.5)
plt.legend()
plt.savefig(os.path.join(SAVE_DIR, 'history.png'))

