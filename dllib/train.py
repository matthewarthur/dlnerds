from .imports import *
from .utils import make_var as make_var
from .model import *
from .lr_sched import *
from .logger import Logger
tqdm.monitor_interval = 0

class Trainer(object):
    def __init__(self, model, datasets, criterion, optimizer, pre_trained=True, batch_size=64, name ='default'):
        self.model = model
        self.datasets = datasets
        self.batch_size = batch_size
        self.train_loader = torch.utils.data.DataLoader(datasets['train'], batch_size=self.batch_size,
                                             shuffle=True, num_workers=4)
        self.val_loader = torch.utils.data.DataLoader(datasets['val'], batch_size=self.batch_size,
                                             shuffle=True, num_workers=4)
        self.criterion = criterion
        self.optimizer = optimizer
        self.pre_trained = pre_trained
        self.name = name
        
        #self.monitor = boilerplate.VisdomMonitor(port=80)
 
        
    def train_model(self, optimizer=None, scheduler=None, cycle_len=None, cycle_mult=1, num_epochs=10):
        since = time.time()
        if not (optimizer is None):
            self.optimizer = optimizer
        best_model_wts = copy.deepcopy(self.model.state_dict())
        best_acc = 0.0
        
        dataset_sizes = {x: len(self.datasets[x]) for x in ['train', 'val']}
        class_names = self.datasets['train'].classes
        dataloaders = {'train':self.train_loader,'val':self.val_loader}

        #save training process to simple Logger function
        if not os.path.isdir('checkpoint'):
            os.mkdir('checkpoint')
        logger = Logger(os.path.join('checkpoint', 'log.txt'), title=self.name)
        logger.set_names(['Learning Rate', 'Train Loss', 'Valid Loss', 'Train Acc.', 'Valid Acc.'])

        for epoch in range(num_epochs):
            print('Epoch {}/{}'.format(epoch, num_epochs - 1))
            print('-' * 10)
            
            # Each epoch has a training and validation phase
            for phase in ['train', 'val']:
                if phase == 'train':
                    # Check if scheduler is present, if so then check if it has apply_batch attribute.  
                    # if scheduler is present and apply_batch is false, then scheduler step
                    # if scheduler is present and doesn't have a apply_batch attribute, then scheduler step
                    if scheduler:
                        if hasattr(scheduler, 'apply_batch'):
                            if not scheduler.apply_batch:
                                scheduler.step()
                        else: scheduler.step()

                    self.model.train(True)  # Set model to training mode
                else:
                    self.model.train(False)  # Set model to evaluate mode

                running_loss = 0.0
                running_corrects = 0

                # Iterate over data.
                for data in tqdm(dataloaders[phase]):
                    # get the inputs
                    inputs, labels = data
                    
                    if phase == 'train':
                        if hasattr(scheduler, 'apply_batch'):
                            if scheduler.apply_batch:
                                scheduler.step()
                        outputs, loss = self.fit_on_batch(inputs,labels,self.criterion,self.optimizer)
                    else:
                        outputs, loss = self.evaluate_on_batch(inputs,labels,self.criterion)
                                        
                    _, preds = torch.max(outputs.data, 1)
                   
                    # statistics
                    running_loss += loss.data[0] * inputs.size(0)
                    running_corrects += torch.sum(preds == labels)

                epoch_loss = running_loss / dataset_sizes[phase]
                epoch_acc = running_corrects / dataset_sizes[phase]

                print('{} Loss: {:.4f} Acc: {:.4f}'.format(
                    phase, epoch_loss, epoch_acc))

                # deep copy the model
                # remember best accuracy and save checkpoint
                if phase == 'val':
                    is_best = epoch_acc > best_acc
                    self.save_checkpoint({
                        'epoch': epoch + 1,
                        'state_dict': self.model.state_dict(),
                        'best_acc': best_acc,
                        'optimizer' : self.optimizer.state_dict(),
                    }, is_best)
                    if epoch_acc > best_acc:
                        best_acc = epoch_acc
                        best_model_wts = copy.deepcopy(self.model.state_dict())

            print()
    
        time_elapsed = time.time() - since
        print('Training complete in {:.0f}m {:.0f}s'.format(
            time_elapsed // 60, time_elapsed % 60))
        print('Best val Acc: {:4f}'.format(best_acc))

        # load best model weights
        self.model.load_state_dict(best_model_wts)
        return self.model
     
    def fit_on_batch(self, x, y, loss_fn, optimizer, metrics=["loss", "acc"]):
        """Trains the model on a single batch of examples.
        This is a training function for a basic classifier. For more complex models,
        you should write your own training function.
        NOTE: Before you call this, make sure to do `model.train(True)`.
        Parameters
        ----------
        model: nn.Module
            The model to train.
        x: Tensor 
            Image tensors should have size (batch_size, in_channels, height, width).
        y: Tensor
            Contains the label indices (not one-hot encoded).
        loss_fn: 
            The loss function to use.
        optimizer: 
            The SGD optimizer to use.
        metrics: list
            Which metrics to compute over the batch.
        Returns
        -------
        dict
            The computed metrics for this batch.
        """
        # zero the parameter gradients
        optimizer.zero_grad()

        # Forward pass
        outputs = self.model(make_var(x))

        # Compute loss
        y_true = make_var(y, dtype=np.int)
        loss = loss_fn(outputs, y_true)

        # Backward pass
        loss.backward()
        optimizer.step()

        return outputs, loss
    
    def evaluate_on_batch(self, x, y, loss_fn=None, metrics=["loss", "acc"]):
        """Evaluates the model on a single batch of examples.

        This is a evaluation function for a basic classifier. For more complex models,
        you should write your own evaluation function.    

        NOTE: Before you call this, make sure to do `model.train(False)`.

        Parameters
        ----------
        model: nn.Module
            Needed to make the predictions.
        x: Tensor or numpy array 
            Image tensors should have size (batch_size, in_channels, height, width).
        y: Tensor or numpy array 
            Contains the label indices (not one-hot encoded)
        loss_fn: optional
            The loss function used to compute the loss. Required when the
            metrics include "loss".
        metrics: list
            Which metrics to compute over the batch.

        Returns
        -------
        dict
            The computed metrics for this batch.
        """

        outputs = self.model(make_var(x, volatile=True))
        y_true = make_var(y, dtype=np.int, volatile=True)
        loss = loss_fn(outputs, y_true)
        
        return outputs, loss
    
    def lr_find(self, start_lr=1e-5, end_lr=10, steps=None):
        """Finds the optimal learning rate for training.
        Typically you'd do this on a model that has not been trained yet.
        However, calling find_lr() on a (partially) trained model is OK too;
        the state of the model and optimizer are preserved so that find_lr()
        won't actually change the model's parameters.
        Parameters
        ----------
        start_lr: float (optional)
            The learning rate to start with (should be quite small).
        end_lr: float (optional)
            The maximum learning rate to try (should be large-ish).
        steps: int (optional)
            How many batches to evaluate, at most. If not specified,
            find_lr() runs for a single epoch. As a rule of thumb, 100
            steps seems to work well.
        """
        self._save_state()
        
        one_epoch = len(self.train_loader)
        epochs = 1
        if steps is None:
            steps = one_epoch
        elif one_epoch < steps:
            epochs = (steps + one_epoch - 1) // one_epoch
       
        #lr_history = []
        #loss_history = []
        history = {}
        iteration = 0
        best_loss = 1e9
        
        lr_decay = 10**((np.log10(end_lr)-np.log10(start_lr))/float(steps))
        lr_value = start_lr
        should_stop = False
        
        print("Trying learning rates between %g and %g over %d steps (%d epochs)" %
              (start_lr, end_lr, steps, epochs))
        
        for epoch in range(epochs):
            if should_stop:
                break
            print('Epoch {}/{}'.format(epoch, epochs - 1))
            print('-' * 10)
                        
            self.model.train(True)  # Set model to training mode
                   
            # Iterate over data.
            for batch_idx, data in tqdm(enumerate(self.train_loader)):
                # get the inputs
                inputs, labels = data
                iteration += 1

                outputs, loss = self.fit_on_batch(inputs,labels,self.criterion,self.optimizer)

                # statistics
                history.setdefault('lr', []).append(lr_value)
                history.setdefault('loss', []).append(loss.data[0])
                history.setdefault('iterations', []).append(iteration)
                #loss_history.append(loss.data[0])
                #lr_history.append(lr_value)
                                
                print('Batch No:{} Learn rate {:.2E} Batch Loss: {:.4f} '.format(
                    batch_idx, lr_value, loss.data[0]))
                
                if loss.data[0] < best_loss:
                    best_loss = loss.data[0]

                if math.isnan(loss.data[0]) or loss.data[0] > best_loss*20 or iteration >= steps - 1:
                    should_stop = True
                    break
                              
                          
                #loss_history_prev = loss.data[0]    

                for param_group in self.optimizer.param_groups:
                    param_group['lr'] *= lr_decay
                lr_value *= lr_decay

        #history = {'loss_hist':loss_history,'lr_hist':lr_history}   
        self.loss_lr_plot(history)         
        self._restore_state()
     
    def plot_lr(self,history):
        '''Helper function to quickly inspect the learning rate schedule.'''
        plt.plot(history['iterations'], self.history['lr'])
        plt.yscale('log')
        plt.xlabel('Iteration')
        plt.ylabel('Learning rate')

    def loss_lr_plot(self,history,figsize=(12, 6)):
        fig = plt.figure(figsize=figsize)
        plt.ylabel("loss", fontsize=16)
        plt.xlabel("learning rate (log scale)", fontsize=16)
        plt.xscale("log")
        plt.plot(history['lr'], history['loss'])
        plt.show()
        
    def _save_state(self):
        state = {}
        state["model"] = copy.deepcopy(self.model.state_dict())
        state["optimizer"] = copy.deepcopy(self.optimizer.state_dict())
        self._saved_state = state

    def _restore_state(self):
        state = self._saved_state
        self.model.load_state_dict(state["model"])
        self.optimizer.load_state_dict(state["optimizer"])
    
    def save_model(self, m, p): torch.save(m.state_dict(), p)

    def load_model(self, m, p): m.load_state_dict(torch.load(p, map_location=lambda storage, loc: storage)) 

    def predict(self, is_test=False):
        dl = self.val_loader
        return predict(self.model, dl)

    def predict_with_targs(self, is_test=False):
        dl = self.val_loader
        return predict_with_targs(self.model, dl)

    def predict_dl(self, dl): return predict_with_targs(self.model, dl)[0]

    def save_checkpoint(self, state, is_best, filename='checkpoint.pth.tar'):
        torch.save(state, self.name+'_'+filename)
        if is_best:
            shutil.copyfile(self.name+'_'+filename, 'model_best.pth.tar')    
    

