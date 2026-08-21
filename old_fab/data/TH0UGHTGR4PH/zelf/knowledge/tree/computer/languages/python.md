# LANGUAGE  

# generators
```
def count_to_n (n):
  i = 0
  while i < n:
    yield i
gen = count_to_n (10)
for p in gen
next (gen)
```
lazily yields one by one  
```
list(gen)
sorted(gen)
```
consumes all, makes into a list / sorted list  

# fstring  

```
f"{num:04d}"
```
format as integer and pad with 0 until 4 digits  


# LIBRARIES  

# Pathlib  
```
from pathlib import Path  
p = Path.cwd()
```
creates a path object from where i ran the script from  
```
output_dir = p/"mind"/"data"
```
the path object automatically creates paths with /.  
```
out_dir.mkdir(parents=True, exist_ok=True)
```
makes itself  
```
existing_shards=sorted(out_dir.glob("shard_*.txt"))
```  
glob: returns a generator.  
*: any text  
?: one char  
**: any folder any depth  
```
p.read_text()
```
reads text (txt, md, csv, json) into a string  
