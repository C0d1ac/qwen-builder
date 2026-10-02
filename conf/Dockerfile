FROM python:3.12-slim
RUN pip install --no-cache-dir huggingface_hub
WORKDIR /conf

RUN hf download \
	Qwen/Qwen3.8-Flash-Next \
	config.json \
	tokenizer.json \
	tokenizer_config.json \
	generation_config.json \
	special_tokens_map.json \
	vocab.json \
	video_preprocessor_config.json \
	preprocessor_config.json \
	model.safetensors.index.json


