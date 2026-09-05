import os

import transformers
from openai import OpenAI
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-30B-A3B")

def show_tokens(text: str):
    tokens = tokenizer.encode(text)
    return [(token, tokenizer.decode(token)) for token in tokens]

for i in range(1000):
    print(f"Token {i}: '{tokenizer.decode(i)}'")


print(show_tokens("DSA steht für"))


template_text = tokenizer.apply_chat_template(
    [{"role": "system", "content": "You are a helpful assistant"}, {"role": "user", "content": "Welche zwei Flüsse prägen hauptsächlich die Landschaft von Askanien?"}],
        tokenize=False,
        add_generation_prompt=True,
        # continue_final_message=True,
        enable_thinking=True
)

def color_token(token: str, i: int):
    sanitized_token = token.replace('\n', '\\textbackslash n').replace("_", "\\_")
    prefix = " " if sanitized_token[0] == " " else ""
    suffix = "\n" if "textbackslash n" in sanitized_token else ""
    return rf"{prefix}\textcolor{{\TokenColor{['A', 'B'][i%2]}}}{{{sanitized_token.strip()}}}{suffix}"

    # return fr"{'\\' if '\n' in token else ''}\textcolor{{\TokenColor{['A', 'B'][i%2]}}}{{{token.replace('\n', 'n').replace("_", "\\_")}}}


res = ""
for i, (id, token) in enumerate(show_tokens(template_text)):
    print(color_token(token, i), end="")
    res += color_token(token, i)

print("--------------")
lines = [f"(*@{line}@*)" for line in res.splitlines()]
print("\n".join(lines))
    # print(fr"{'\\' if '\n' in token else ''}\textcolor{{\TokenColor{['A', 'B'][i%2]}}}{{{token.replace('\n', 'n').replace("_", "\\_")}}}", end="")

breakpoint()


# client = OpenAI(base_url="https://ki-chat.uni-mainz.de/api/", api_key=os.environ["JGU_API_KEY"])
# completion = client.chat.completions.create(
#   model="Qwen3 235B VL",
#   messages=[
#     {"role": "assistant", "content": "My favorite day of the week is"},
#   ],
#   top_logprobs=20,
#   logprobs=True
# )


breakpoint()

