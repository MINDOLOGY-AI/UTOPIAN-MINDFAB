# interp  
the complete interpretability pipeline we run on one model  

we go from simplistic, low abstraction methods gradually to more additional weights, high abstraction methods  
we can have multiple different methods labeling the same data, so we can cross check them  

# initial analysis
just a simple precheck  

## static analysis
we run a basic static analysis on activations and weights to gather their average and variance magnitudes.  

## dynamic analysis  
patterns of activations changes? see what areas get mapped to what?  

# direct label  

here we directly label the actual activations and weights with no external probes. we assume a neuron level view.  

## MLP neuron label

label MLP neuron firing directly. no grouping or training.  


# activation block

 label activations some method of grouping activations into blocks which are units of labeling.  

numerical criteria: sparsity and recon.  

## KNN

we use KNN to find blocks.  

## Cross Layer KNN

we try to group perhaps like say 4 layer's activations at a time by simply concating them? sort of like WCCs. the idea is you directly compress either circuits or repeated concepts.  

# SAEs  

we decompose the activations into multiple features. by the linear representation hypothesis we believe that features are concepts the model computes in parallel.  

numerical criteria: sprasity and recons.

## normal SAE  

## topK SAE

# WCCs  


# architecture  

tokenized dataset -(LLM hooked inference)-> activations  
activations -(train_probe)-> pred_activations  
probe_context -(api labeling) -> interp  

classes that are extractable from different methods:  
1: hooked LLM: returns activations  
2: training loop: train probe on activations (same input output). record firing strength.  
3:


# interp context format  

we can use a unified prompt and api call format  
```
{
    feature_num: int
    {
        zero_frac: float      # fraction of tokens where unit == 0 (catches dead units)
        firing_q: [float]     # value at p = [0, .01, .1, .25, .5, .75, .9, .99, 1], derived post-hoc from sample_contexts
    }
    [{...
        context_id: int
        firing strength: int
    }]
}
```

# to be decided:  

we don't jsut want the max firing strength. what else levels do we want.  

auto causality experiments?  
