"""
Chat with the local Qwen3.5-4B model (text branch).
Conversation history is kept in RAM.

Run from UTOPIAN-MINDFAB root as a module:
    python -m mind.EV0K3.Qwen3_5_4b.run.chat
"""

import logging

import torch

from mind.EV0K3.Qwen3_5_4b.run.config import QWEN3_5_4B_CONFIG
from mind.EV0K3.Qwen3_5_4b.run.loader import build_model_and_tokenizer

# use SDPA (flash kernels) for the full-attention layers in chat; the config
# default stays eager so interp code is unaffected
QWEN3_5_4B_CONFIG.use_flash_attention = True

# bitsandbytes spams "MatMul8bitLt: inputs will be cast..." once per int8 matmul; harmless
logging.getLogger("bitsandbytes").setLevel(logging.ERROR)

# effectively uncapped for chat; generation still stops at EOS (<|im_end|>)
MAX_NEW_TOKENS = 8192

# Qwen3.5 thinks by default; the chat template can disable it
ENABLE_THINKING = False


@torch.no_grad()
def generate(
    model,
    input_ids,
    attention_mask,
    max_new_tokens=500,
    temperature=0.7,
    top_p=0.9,
    do_sample=True,
    eos_token_ids=None,
    on_token=None,
):
    """
    Generate tokens with the hybrid (KV + recurrent) cache.

    input_ids:     (batch, seq_len)
    attention_mask:(batch, seq_len)
    on_token:      optional callback called with the full generated tensor
                   after each new token (used for streaming output)
    """
    device = input_ids.device
    past_key_values = None
    generated = input_ids.clone()

    for _ in range(max_new_tokens):
        if past_key_values is None:
            # first forward: process full prompt
            logits, _, past_key_values = model(
                input_ids=generated,
                attention_mask=attention_mask,
            )
        else:
            # subsequent forwards: only the last token
            logits, _, past_key_values = model(
                input_ids=generated[:, -1:],
                attention_mask=attention_mask,
                past_key_values=past_key_values,
            )

        next_token_logits = logits[:, -1, :]

        if do_sample:
            if temperature != 1.0 and temperature > 0:
                next_token_logits = next_token_logits / temperature

            # top-p (nucleus) sampling
            if top_p is not None and top_p < 1.0:
                sorted_logits, sorted_indices = torch.sort(
                    next_token_logits, descending=True
                )
                cumulative_probs = torch.cumsum(
                    torch.softmax(sorted_logits, dim=-1), dim=-1
                )

                # remove tokens with cumulative prob above threshold
                sorted_indices_to_remove = cumulative_probs > top_p
                # keep at least one token
                sorted_indices_to_remove[..., 1:] = sorted_indices_to_remove[..., :-1].clone()
                sorted_indices_to_remove[..., 0] = False

                indices_to_remove = sorted_indices_to_remove.scatter(
                    -1, sorted_indices, sorted_indices_to_remove
                )
                next_token_logits = next_token_logits.masked_fill(indices_to_remove, float('-inf'))

            probs = torch.softmax(next_token_logits, dim=-1)
            next_token = torch.multinomial(probs, num_samples=1)
        else:
            next_token = next_token_logits.argmax(dim=-1, keepdim=True)

        generated = torch.cat([generated, next_token], dim=-1)
        attention_mask = torch.cat(
            [
                attention_mask,
                torch.ones((attention_mask.size(0), 1), device=device, dtype=attention_mask.dtype),
            ],
            dim=-1,
        )

        if on_token is not None:
            on_token(generated)

        if eos_token_ids is not None and next_token.item() in eos_token_ids:
            break

    return generated


def main():
    print("Loading Qwen3.5-4B...")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, tokenizer, config = build_model_and_tokenizer(device=device)
    print(f"Model loaded on {device}\n")

    # stop on <|im_end|> (config eos) or the tokenizer's own eos
    eos_token_ids = {config.eos_token_id, tokenizer.eos_token_id}
    eos_token_ids.discard(None)

    messages = []
    print("Qwen3.5-4B chat. Type 'quit', 'exit', or 'q' to exit.\n")

    while True:
        user_text = input("You: ").strip()
        if user_text.lower() in {"quit", "exit", "q"}:
            break

        messages.append({"role": "user", "content": user_text})

        # build prompt with the Qwen chat template
        encoded = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            return_tensors="pt",
            add_generation_prompt=True,
            return_dict=True,
            enable_thinking=ENABLE_THINKING,
        )
        prompt_tensor = encoded.input_ids.to(device)

        # attention mask: all real tokens
        attention_mask = encoded.attention_mask.to(device)

        # stream: re-decode the whole reply each step and print only the new
        # text, so multi-token characters never get mangled
        prompt_len = prompt_tensor.shape[-1]
        printed = [0]

        def stream(generated):
            text = tokenizer.decode(generated[0][prompt_len:], skip_special_tokens=True)
            print(text[printed[0]:], end="", flush=True)
            printed[0] = len(text)

        print("Bot: ", end="", flush=True)
        outputs = generate(
            model,
            prompt_tensor,
            attention_mask,
            max_new_tokens=MAX_NEW_TOKENS,
            temperature=0.7,
            top_p=0.9,
            do_sample=True,
            eos_token_ids=eos_token_ids,
            on_token=stream,
        )
        print("\n")

        # decode only the new tokens
        reply_ids = outputs[0][prompt_len:]
        reply = tokenizer.decode(reply_ids, skip_special_tokens=True)

        messages.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
