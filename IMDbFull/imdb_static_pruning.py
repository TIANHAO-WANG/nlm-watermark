# -*- coding: utf-8 -*-
"""model_pruning.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1CNzRzed1SA0Ia3H7TB16f-eqdUaKOeJq
"""

from google.colab import drive
drive.mount("/content/drive/")

import torch
from torchtext import data , datasets,vocab
import torchtext
import os
import numpy as np
from torch import nn
from torch.autograd import Variable
import torch.nn.functional as F
import spacy
import pickle
import glob
from torch.optim.lr_scheduler import StepLR
import random
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split

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

# load trained model
model = IMDBRnn(n_vocab,n_hidden,2,bs=bs)
model.load_state_dict(torch.load('/content/drive/My Drive/cs281_final_project/my_best_lstm2'), strict=False)

print(model)

"""Next we find out the lowest n% weights and mark them as 0"""

def change_weight(model, p):
  state_dict = model.state_dict()
  new_dict = {}
  for layer in state_dict:
    wt = state_dict[layer]
    threshold = np.percentile(torch.abs(wt), p)
    wt[torch.abs(wt)<threshold] = 0
    new_dict[layer] = wt
  return new_dict

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

def test_acc_after_prune(model, p, vm_iter, test_iter, message):
  new_model = IMDBRnn(n_vocab,n_hidden,2,bs=bs)
  if p>0:
    new_dict = change_weight(model,p)
    new_model.load_state_dict(new_dict)
    new_model = new_model.cuda()
  else:
    new_model = model.cuda()
  print("Test Accuracy")
  print("===========================================================")
  loss , accuracy1 = fit(1, new_model,test_iter,phase='validation')
  print(" Accuracy: {}".format(accuracy1))
  print(message+"watermark Accuracy")
  print("===========================================================")
  loss , accuracy2 = fit(1,new_model, vm_iter,phase='validation')
  print(" Accuracy: {}".format(accuracy2))

with open("/content/drive/My Drive/cs281_final_project/imdb_watermark.pkl","rb") as f:
  watermark_list = pickle.load(f)
pattern_watermark = watermark_list['pattern']
watermark_instance_random = watermark_list['instance_random']
watermark_instance_irrelevant = watermark_list['instance_irrelevant']

pattern_watermark_dat = myDataset(pattern_watermark, TEXT, LABEL)
watermark_instance_random_dat = myDataset(watermark_instance_random, TEXT, LABEL)
watermark_instance_irrelevant_dat = myDataset(watermark_instance_irrelevant, TEXT, LABEL)
bs = 32

model = IMDBRnn(n_vocab,n_hidden,2,bs=bs)
model.cuda()
model.load_state_dict(torch.load('/content/drive/My Drive/cs281_final_project/pattern_train_from_scratch'), strict=False)
pattern_iter, instance_random_iter, instance_irrelevant_iter, test_iter = torchtext.data.BucketIterator.splits((pattern_watermark_dat,
                                                                                          watermark_instance_random_dat,
                                                                                          watermark_instance_irrelevant_dat, 
                                                                                          test_dat), 
                                                                         batch_size = bs, repeat = False,
                                                                         sort_key = lambda x : len(x.text)) 
wm_loss , wm_acc = fit(1,model,instance_irrelevant_iter,phase='validation')
print(" Accuracy of watermark is {}".format(wm_acc))

for p in np.linspace(0, 95,20):  
  # prunning from no prunning to 95%, using 5% step size
  print("percentile used for pruning is ", p)
  model = IMDBRnn(n_vocab,n_hidden,2,bs=bs)
  model.load_state_dict(torch.load('/content/drive/My Drive/cs281_final_project/pattern_train_from_scratch'), strict=False)
  pattern_iter, test_iter = torchtext.data.BucketIterator.splits((pattern_watermark_dat,
                                                                  test_dat), 
                                                                  batch_size = bs, repeat = False,
                                                                  sort_key = lambda x : len(x.text))  
  test_acc_after_prune(model, p, pattern_iter,test_iter, "pattern based ")
  print("\n")

for p in np.linspace(0, 95,20):  
  # prunning from no prunning to 95%, using 5% step size
   print("percentile used for pruning is ", p)
   model = IMDBRnn(n_vocab,n_hidden,2,bs=bs)
   model.load_state_dict(torch.load('/content/drive/My Drive/cs281_final_project/random_train_from_scratch'), strict=False)
   instance_random_iter, test_iter = torchtext.data.BucketIterator.splits((watermark_instance_random_dat,
                                                                   test_dat), 
                                                                  batch_size = bs, repeat = False,
                                                                  sort_key = lambda x : len(x.text))  
   test_acc_after_prune(model, p, instance_random_iter,test_iter, "random ")
   print("\n")

for p in np.linspace(0, 95,20):  
  # prunning from no prunning to 95%, using 5% step size
  print("percentile used for pruning is ", p)
  model = IMDBRnn(n_vocab,n_hidden,2,bs=bs)
  model.load_state_dict(torch.load('/content/drive/My Drive/cs281_final_project/irrelevant_train_from_scratch'), strict=False)  
  instance_irrelevant_iter, test_iter = torchtext.data.BucketIterator.splits((watermark_instance_irrelevant_dat, 
                                                                         test_dat), 
                                                                         batch_size = bs, repeat = False,
                                                                         sort_key = lambda x : len(x.text))
  test_acc_after_prune(model, p, instance_irrelevant_iter,test_iter, "instance irrelevant ")
  print("\n")