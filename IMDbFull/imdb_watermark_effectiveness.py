# -*- coding: utf-8 -*-
"""Watermark_accuracy.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1KJVI4MT5PlieiZP2DChkrXr-03yWEMLg
"""

from google.colab import drive
drive.mount("/content/drive/")

import torch
from torchtext import data, datasets, vocab
import torchtext
import os
from torch import nn
from torch.autograd import Variable
import torch.nn.functional as F
import spacy
import pickle
import glob
from torch.optim.lr_scheduler import StepLR
import random
import matplotlib.pyplot as plt

spacy.load('en')
torch.cuda.empty_cache()

with open("/content/drive/My Drive/cs281_final_project/imdb_splitted.pkl","rb") as f:
  data_list = pickle.load(f)
TEXT = data.Field(lower=True,tokenize='spacy')
LABEL = data.Field(sequential=False,)
train = data_list["train"]
val = data_list["validation"]
test = data_list["test"]

class myDataset(torchtext.data.Dataset):
    def __init__(self, df, text_field, label_field,**kwargs):
        fields = [('text', text_field), ('label', label_field)]
        examples = df
        super(myDataset, self).__init__(examples, fields, **kwargs)

train_dat = myDataset(train, TEXT,LABEL)
val_dat = myDataset(val, TEXT,LABEL)
test_dat = myDataset(test, TEXT,LABEL)

TEXT.build_vocab(train_dat,vectors='glove.6B.300d',max_size=25000)
LABEL.build_vocab(train_dat,)

bs = 32
train_iter, valid_iter, test_iter = torchtext.data.BucketIterator.splits((train_dat, val_dat, test_dat), 
                                                                         batch_size = bs, repeat = False,
                                                                         sort_key = lambda x : len(x.text))

n_vocab = len(TEXT.vocab)
n_hidden = 300

class IMDBRnn(nn.Module):
    def __init__(self,vocab,hidden_size,n_cat,bs=1,nl=2):
        super().__init__()
        self.hidden_size = hidden_size
        self.bs = bs
        self.nl = nl
        self.e = nn.Embedding(n_vocab,hidden_size)
        self.rnn = nn.LSTM(hidden_size,hidden_size,nl)
        self.bn1 = nn.BatchNorm1d(hidden_size)
        self.fc2 = nn.Linear(hidden_size,n_cat)
        self.bn2 = nn.BatchNorm1d(n_cat)
        self.softmax = nn.LogSoftmax(dim=-1)
        
    def forward(self,inp):
        bs = inp.size()[1]
        if bs != self.bs:
            self.bs = bs
        e_out = self.e(inp)
        h0 = c0 = Variable(e_out.data.new(*(self.nl,self.bs,self.hidden_size)).zero_())
        rnn_o,_ = self.rnn(e_out,(h0,c0)) 
        rnn_o = rnn_o[-1]
        rnn_o = self.bn1(rnn_o)
        fc = F.dropout(self.fc2(rnn_o), 0.30)
        fc = self.bn2(fc)
        return self.softmax(fc)

model = IMDBRnn(n_vocab,n_hidden,2,bs=bs)
model.e.weight.data = TEXT.vocab.vectors
model.load_state_dict(torch.load('/content/drive/My Drive/cs281_final_project/random_train_from_scratch'), strict=False)
model = model.cuda()

is_cuda = torch.cuda.is_available()
optimizer = torch.optim.Adam(model.parameters(),lr=1e-2)
# after every 1 epoch, lr = lr*gamma
scheduler = StepLR(optimizer, step_size=1, gamma = 0.9)

def fit(epoch,model,data_loader,phase='training',volatile=False):
    if phase == 'training':
        model.train()
    if phase == 'validation':
        model.eval()
        volatile=True
    running_loss = 0.0
    running_correct = 0
    for batch_idx , batch in enumerate(data_loader):
        batch.label = batch.label-1
        text , target = batch.text , batch.label
        if is_cuda:
            text,target = text.cuda(),target.cuda()
        
        if phase == 'training':
            optimizer.zero_grad()
        output = model(text)
       
        loss = F.nll_loss(output,target)
        
        running_loss += F.nll_loss(output,target,size_average=False).data
        preds = output.data.max(dim=1,keepdim=True)[1]
        running_correct += preds.eq(target.data.view_as(preds)).cpu().sum()
        if phase == 'training':
            loss.backward()
            optimizer.step()
    
    loss = running_loss/len(data_loader.dataset)
    accuracy = 100. * running_correct/len(data_loader.dataset)
    
    print(f'{phase} loss is {loss:{5}.{2}} and {phase} accuracy is {running_correct}/{len(data_loader.dataset)}{accuracy:{10}.{4}}')
    return loss,accuracy

## Get watermark data
with open("/content/drive/My Drive/cs281_final_project/imdb_watermark.pkl","rb") as f:
  watermark_list = pickle.load(f)
watermark = watermark_list['pattern']
#watermark_instance_meaningful = watermark_list['instance_meaningful'] 
#watermark_instance_random = watermark_list['instance_random']
#watermark_instance_irrelevant = watermark_list['instance_irrelevant']

## Wrap watermark into dataset
watermark_dat = myDataset(watermark, TEXT, LABEL)
bs = 32
watermark_iter, test_iter = torchtext.data.BucketIterator.splits((watermark_dat, test_dat), 
                                                                         batch_size = bs, repeat = False,
                                                                         sort_key = lambda x : len(x.text))

## No water mark
test_loss , test_acc = fit(1,model,test_iter,phase='validation')
print(" Accuracy of Test dataset is {}".format(test_acc))
wm_loss , wm_acc = fit(1,model,watermark_iter,phase='validation')
print(" Accuracy of watermark is {}".format(wm_acc))

def mix_data(examples1, examples2):
  examples = (examples1+examples2)
  random.shuffle(examples)
  return myDataset(examples, TEXT, LABEL)

mixed = mix_data(train, watermark)
mixed_iter, test_iter = torchtext.data.BucketIterator.splits((mixed, test_dat), 
                                                                         batch_size = bs, repeat = False,
                                                                         sort_key = lambda x : len(x.text))

## Pre-train
torch.cuda.empty_cache()
train_losses , train_accuracy = [],[]
val_losses , val_accuracy = [],[]
best_model_dict = None
for epoch in range(10):
    scheduler.step()
    best_val_acc = 0
    print("epoch {}".format(epoch))
    epoch_loss, epoch_accuracy = fit(epoch,model,mixed_iter,phase='training')
    val_epoch_loss , val_epoch_accuracy = fit(epoch,model,valid_iter,phase='validation')
    if val_epoch_accuracy > best_val_acc:
      best_model_dict = model.state_dict()
    train_losses.append(epoch_loss)
    train_accuracy.append(epoch_accuracy)
    val_losses.append(val_epoch_loss)
    val_accuracy.append(val_epoch_accuracy)

## Pre-train accuracy
test_loss , test_accuracy = fit(1,model,test_iter,phase='validation')
print(" Accuracy of Test dataset is {}".format(test_accuracy))
test_loss , test_accuracy = fit(1,model,watermark_iter,phase='validation')
print(" Accuracy of watermark is {}".format(test_accuracy))

## From scratch
torch.cuda.empty_cache()
model = IMDBRnn(n_vocab,n_hidden,2,bs=bs)
model.e.weight.data = TEXT.vocab.vectors
model.load_state_dict(torch.load('/content/drive/My Drive/cs281_final_project/init_state'), strict=False)
model = model.cuda()
is_cuda = torch.cuda.is_available()
optimizer = torch.optim.Adam(model.parameters(),lr=1e-2)
# after every 1 epoch, lr = lr*gamma
scheduler = StepLR(optimizer, step_size=1, gamma = 0.9)

train_loss, train_acc = fit(1, model, train_iter, phase="validation")
test_loss , test_acc = fit(1,model,test_iter,phase='validation')
wm_loss , wm_acc = fit(1,model,watermark_iter,phase='validation')

train_losses , train_accuracy = [],[train_acc]
val_losses , val_accuracy = [],[test_acc]
wm_losses, wm_accuracy = [],[wm_acc]
best_model_dict = None
for epoch in range(30):
    scheduler.step()
    best_val_acc = 0
    print("epoch {}".format(epoch))
    epoch_loss, epoch_accuracy = fit(epoch,model,mixed_iter,phase='training')
    val_epoch_loss , val_epoch_accuracy = fit(epoch,model,valid_iter,phase='validation')
    wm_epoch_loss, wm_epoch_accuracy = fit(epoch, model, watermark_iter, phase='validation')
    if val_epoch_accuracy > best_val_acc:
      best_model_dict = model.state_dict()
    train_losses.append(epoch_loss)
    train_accuracy.append(epoch_accuracy)
    val_losses.append(val_epoch_loss)
    val_accuracy.append(val_epoch_accuracy)
    wm_losses.append(wm_epoch_loss)
    wm_accuracy.append(wm_epoch_accuracy)

## From Scratch accuracy
test_loss , test_accuracy = fit(1,model,test_iter,phase='validation')
print(" Accuracy of Test dataset is {}".format(test_accuracy))
test_loss , test_accuracy = fit(1,model,watermark_iter,phase='validation')
print(" Accuracy of watermark is {}".format(test_accuracy))

plt.figure(figsize=(12,8))
plt.plot(range(len(train_accuracy)), train_accuracy, label = "Train Accuracy", color='b')
plt.plot(range(len(val_accuracy)), val_accuracy, label="Test Accuracy", color = 'r')
plt.plot(range(len(wm_accuracy)), wm_accuracy, label="Water Mark Accuracy", color = 'g')
plt.xlabel("Epoch", fontsize=16)
plt.ylabel("Accuracy", fontsize=16)
plt.legend(fontsize=16)
plt.title("Accuracy of Training, Testing, Random Instance-Based \nWatermark Dataset through Each Epoch", fontsize=20)
plt.savefig("/content/drive/My Drive/cs281_final_project/Accuracy_pic_random_instance_based.png")
plt.show()