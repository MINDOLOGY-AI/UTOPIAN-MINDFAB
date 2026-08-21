Princeton Continual Factoid Memorization Benchmark

## What It Is
A two-stage continual learning benchmark for language models. The model first memorizes a set of facts ($D_A$), then is trained on a second set ($D_B$), and finally is tested on how much of $D_A$ it still remembers. The metric is **retention**: the percentage of $D_A$ facts the model answers correctly after learning $D_B$.

## What It Is Made Of

| Component | Description |
|-----------|-------------|
| **PopQA** | 1,385 long-tail question-answer pairs about obscure entities. Base LLMs typically score ~19% on these. |
| **TriviaQA** | General-knowledge QA pairs. Used as $D_A$ (the "old" knowledge to protect). |
| **LAMA** | 40K+ templated facts from Wikidata (e.g., "Obama was born in ___"). |
| **EntityQuestions** | 22K question-answer pairs derived from Wikidata. |
| **KVR (Key-Value Recall)** | Synthetic task: memorize arbitrary key→value pairs (e.g., "XYZ: ABC"). Tests raw memorization capacity. |

The benchmark combines these into a two-stage pipeline: train on $D_A$ (general facts), then train on $D_B$ (obscure facts), then evaluate retention of $D_A$.

## How Big It Is
- **PopQA (long-tail)**: 1,385 QA pairs
- **TriviaQA**: 95K total (benchmark uses a subset)
- **LAMA**: 40K+ facts across 41 relations
- **EntityQuestions**: 22K QA pairs
- **KVR**: 2,000 synthetic key-value pairs

In practice, the two-stage experiments use **~2,000 facts per stage** for the core results.

## Top 3 Algorithms: Formulas & Explanations

---

### 1. REMIX (Best)

**Core idea:** During fine-tuning on $D_B$, mix the batch with random word sequences and generic pretraining data. The random noise acts as a regularizer that prevents catastrophic forgetting without sacrificing new learning.

**Loss:**

$$\mathcal{L}_{\text{REMIX}} = \mathbb{E}_{x \sim \text{Mix}(D_B, \text{RWS}, \text{K-Pile})} \left[ -\log p_\theta(x_{t+1} \mid x_{\leq t}) \right]$$

**Term-by-term:**

| Symbol | Meaning |
|--------|---------|
| $\text{Mix}(D_B, \text{RWS}, \text{K-Pile})$ | A mixed batch sampled from three sources: the new fact corpus $D_B$, random word sequences (RWS), and a generic pretraining corpus (K-Pile) |
| $p_\theta(x_{t+1} \mid x_{\leq t})$ | The model's predicted probability of the next token, given all previous tokens |
| $-\log p_\theta$ | Standard next-token cross-entropy loss |

**Why it works:** Random word sequences have no semantic structure, so the model cannot overfit to them. They force the model to keep its general pretraining representations "alive" while learning $D_B$. The generic pretraining data anchors the model to its original distribution.

**Scores (retention of $D_A$):**

| Dataset | Retention |
|---------|-----------|
| KVR | 67.4% |
| PopQA | 85.7% |
| TriviaQA | 88.4% |

---

### 2. EWC (Elastic Weight Consolidation)

**Core idea:** After training on $D_A$, compute how "important" each parameter is for $D_A$ (Fisher Information). During $D_B$ training, penalize large changes to important parameters.

**Loss:**

$$\mathcal{L}_{\text{EWC}} = \mathcal{L}_{\text{CE}}(D_B) + \lambda \sum_{i} F_i \left( \theta_i - \theta_i^* \right)^2$$

**Term-by-term:**

| Symbol | Meaning |
|--------|---------|
| $\mathcal{L}_{\text{CE}}(D_B)$ | Standard cross-entropy loss on the new fact corpus $D_B$ |
| $\lambda$ | Regularization strength (hyperparameter) |
| $\sum_{i}$ | Sum over all model parameters indexed by $i$ |
| $F_i$ | **Fisher Information** for parameter $i$: $F_i = \mathbb{E}_{x \sim D_A} \left[ \left( \frac{\partial \log p_{\theta^*}(x)}{\partial \theta_i} \right)^2 \right]$ — measures how sensitive $D_A$ loss is to changes in parameter $i$ |
| $\theta_i$ | Current value of parameter $i$ during $D_B$ training |
| $\theta_i^*$ | "Anchor" value of parameter $i$ after training on $D_A$ (frozen reference) |
| $(\theta_i - \theta_i^*)^2$ | Squared distance from the anchor — penalizes drift |

**Why it works:** Parameters with high Fisher Information are "critical" for $D_A$. EWC lets the model freely change unimportant parameters (learn $D_B$) while locking down important ones (protect $D_A$).

**Scores (retention of $D_A$):**

| Dataset | Retention |
|---------|-----------|
| KVR | 27.3% |
| PopQA | 52.1% |
| TriviaQA | 48.9% |

---

### 3. Behavior Regularization (KL to Frozen Model)

**Core idea:** During $D_B$ training, force the model's output distribution to stay close to the frozen original model's distribution. If the model still behaves like the old model on arbitrary inputs, it hasn't forgotten $D_A$.

**Loss:**

$$\mathcal{L}_{\text{BR}} = \mathcal{L}_{\text{CE}}(D_B) + \lambda \cdot \text{KL}\left( p_{\theta}(\cdot \mid x) \;\|\; p_{\theta^*}(\cdot \mid x) \right)$$

**Term-by-term:**

| Symbol | Meaning |
|--------|---------|
| $\mathcal{L}_{\text{CE}}(D_B)$ | Standard cross-entropy loss on the new fact corpus $D_B$ |
| $\lambda$ | Regularization strength (hyperparameter) |
| $\text{KL}(p_{\theta} \| p_{\theta^*})$ | **Kullback-Leibler divergence** between the current model's output distribution and the frozen original model's output distribution |
| $p_{\theta}(\cdot \mid x)$ | Current model's probability distribution over the vocabulary for input $x$ |
| $p_{\theta^*}(\cdot \mid x)$ | Frozen original model's probability distribution (after $D_A$ training) for the same input $x$ |
| $x$ | Sampled from a "retain set" (often $D_A$ itself or generic pretraining data) |

**Why it works:** KL divergence measures how much two distributions differ. By minimizing it, the model learns $D_B$ while keeping its behavior on all other inputs nearly identical to the original. The catch: if $D_B$ directly contradicts $D_A$, the model can't satisfy both terms and collapses.

**Scores (retention of $D_A$):**

| Dataset | Retention |
|---------|-----------|
| KVR | 17.5% |
| PopQA | 40.7% |
| TriviaQA | 38.9% |

---

### Baseline: Naïve Fine-Tuning (No Mixing)

**Loss:**

$$\mathcal{L}_{\text{naïve}} = \mathcal{L}_{\text{CE}}(D_B)$$

Just standard cross-entropy on $D_B$. Nothing protects $D_A$. This is the lower bound.

**Scores (retention of $D_A$):**

| Dataset | Retention |
|---------|-----------|
| KVR | 17.8% |
| PopQA | 46.0% |
| TriviaQA | 37.8% |


## Important Caveat
The benchmark tests **exact-string memorization**, not generalization. The authors note: *"For factoid datasets, each example is an isolated fact to be memorized exactly, therefore the notion of generalization does not apply."* If you paraphrase the question, the model may fail even if "retention" looks good.

## Links
- Paper: *"Continual Memorization for Language Modeling"* (Princeton NLP)
- Code: `github.com/princeton-nlp/continual-factoid-memorization`
- PopQA data: `jacquelinehe/long-tail-popqa` on HuggingFace
