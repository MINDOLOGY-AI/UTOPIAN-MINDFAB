# interp  
the complete interpretability pipeline we run on one model  

we go from simplistic, low abstraction methods gradually to more additional weights, high abstraction methods  
we can have multiple different methods labeling the same data, so we can cross check them  

# activation block

 label activations directly. we need some method of grouping activations into blocks which are units of labeling.  

numerical criteria: sparsity and recon.  

## KNN



# MLP neuron Label

label MLP neuron firing directly. no grouping or training.  

# static analysis
we run a basic static analysis on activations and weights to gather their average and variance magnitudes.  


# SAEs  

we t
## normal SAE  

## topK SAE

# WCCs  


# architecture  

tokenized dataset -(LLM hooked inference)-> activations  
activations -(train_probe)-> pred_activations  
probe_context -(api labeling) -> interp  


