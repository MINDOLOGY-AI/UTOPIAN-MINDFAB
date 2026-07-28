import torch
import mind.SYN4P5E.train.train_helpers as train_helpers
import time


# simple train, without all the advanced settings  
# no batch epoch save load
# no printing
# assumes a supervised x, y data format  

def simple_train(
    model,
    dataset,
    batch_size,
    optimizer,
    loss_fn,
    epochs,
    save_path,
    batches_per_log,
    batches_per_save
):
    model.cuda()
    model.train()
    losses = {"train": []}
    for cur_epoch in range(epochs):
        dataloader = train_helpers.dataset_to_dataloader(dataset,batch_size,cur_epoch)
        for cur_batch, (x,y) in enumerate(dataloader):
            start_time = time.time()
            x = x.to('cuda')
            y = y.to('cuda')
            pred = model(x)
            loss = loss_fn (pred, y)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            if (cur_batch+1) % batches_per_log == 0:
                losses["train"].append(loss.item())
                train_helpers.log_batch(start_time, cur_epoch,cur_batch,epochs,len(dataloader),losses)
            if (cur_batch+1) % batches_per_save == 0:
                train_helpers.save_checkpoint(save_path,model,optimizer,None,cur_epoch,cur_batch,losses)
                losses = {"train": []}
