from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct-AWQ"
BASE_MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"

DEFAULT_PROMPT = (
    "What application is open and what is the user doing? "
    "List any important text, filenames, URLs, or numbers visible. "
    "Be concise — 3-5 sentences max."
)

BROWSER_PROMPT = (
    "Extract all visible text from this browser screenshot. "
    "Include: the URL, page title, all readable body text, headings, links, search queries, and any important numbers or data. "
    "Output as plain text, preserving the content as-is."
)

BROWSER_PROCESSES = {"chrome", "msedge", "firefox", "opera", "brave", "iexplore"}


class QwenVisionClient:
    def __init__(self):
        self._model = None
        self._processor = None

    def _load(self):
        if self._model is not None:
            return
        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
        import torch

        # low_cpu_mem_usage=True loads shards directly to GPU — avoids holding
        # the full model in system RAM during loading (prevents the 8GB RAM spike)
        load_kwargs = dict(
            torch_dtype=torch.float16,
            device_map="cuda:0",   # put everything on GPU, no CPU offload
            low_cpu_mem_usage=True,
        )

        try:
            logger.info("Loading Qwen2.5-VL-3B-AWQ...")
            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                MODEL_ID, **load_kwargs
            )
        except Exception:
            logger.warning("AWQ model failed, falling back to fp16 base model")
            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                BASE_MODEL_ID, **load_kwargs
            )

        # Release any CPU RAM used during loading
        import gc
        gc.collect()
        torch.cuda.empty_cache()

        self._processor = AutoProcessor.from_pretrained(
            BASE_MODEL_ID, min_pixels=64*28*28, max_pixels=384*28*28
        )
        try:
            import torch
            self._model = torch.compile(self._model, mode="reduce-overhead")
            logger.info("torch.compile applied.")
        except Exception as e:
            logger.warning(f"torch.compile skipped: {e}")
        logger.info("Qwen2.5-VL loaded.")

    def generate(self, prompt: str, system: str = "") -> str:
        """Text-only generation — no image. Used for summaries."""
        self._load()
        import torch

        content = f"{system}\n\n{prompt}" if system else prompt
        messages = [{"role": "user", "content": [{"type": "text", "text": content}]}]
        text = self._processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self._processor(text=[text], return_tensors="pt").to(self._model.device)

        try:
            with torch.no_grad():
                output_ids = self._model.generate(**inputs, max_new_tokens=200)
            trimmed = output_ids[:, inputs["input_ids"].shape[1]:]
            return self._processor.batch_decode(trimmed, skip_special_tokens=True)[0]
        finally:
            del inputs
            torch.cuda.empty_cache()

    def analyze(self, image_path: str | Path, prompt: str | None = None, process_name: str = "") -> str:
        if prompt is None:
            is_browser = any(p in process_name.lower() for p in BROWSER_PROCESSES)
            prompt = BROWSER_PROMPT if is_browser else DEFAULT_PROMPT
        self._load()
        from qwen_vl_utils import process_vision_info
        import torch

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": str(image_path)},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        text = self._processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self._processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self._model.device)

        try:
            with torch.no_grad():
                output_ids = self._model.generate(**inputs, max_new_tokens=100)
            trimmed = output_ids[:, inputs["input_ids"].shape[1]:]
            return self._processor.batch_decode(trimmed, skip_special_tokens=True)[0]
        finally:
            del inputs
            torch.cuda.empty_cache()
