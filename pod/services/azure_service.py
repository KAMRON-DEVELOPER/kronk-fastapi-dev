from typing import Dict, List

import aiohttp
from settings.my_config import get_settings


async def azure_translate_text(texts: List[str], from_lang: str = "en", to_lang: str = "uz") -> List[Dict]:
    """
    Translates a list of texts from one language to another using Azure Translator.
    """
    headers = {
        "Ocp-Apim-Subscription-Key": get_settings().AZURE_TRANSLATOR_KEY,
        "Ocp-Apim-Subscription-Region": get_settings().AZURE_TRANSLATOR_REGION,
        "Content-Type": "application/json",
    }
    params = {"api-version": "3.0", "from": from_lang, "to": to_lang}
    body = [{"text": text} for text in texts]

    async with aiohttp.ClientSession() as session:
        async with session.post(get_settings().AZURE_TRANSLATOR_ENDPOINT, params=params, headers=headers, json=body) as response:
            if response.status == 200:
                return await response.json()
            else:
                error_message = await response.text()
                raise Exception(f"Translation API Error: {error_message}")


# from typing import Optional
# from deepl import DeepLClient, TextResult
# from deepl.deepl_client import WriteResult
#
# from apps.settings.config import get_settings
#
#
# def get_deepl_client():
#     return DeepLClient(auth_key=get_settings().DEEPL_API_KEY)
#
#
# def deepl_translate_text(text: str, context: Optional[str], target_lang: Optional[str] = "UZ") -> TextResult | list[TextResult]:
#     return get_deepl_client().translate_text(text=text, target_lang=target_lang, context=context)
#
#
# def deepl_rephrase_text(text: str, style: Optional[str] = None, tone: Optional[str] = None) -> WriteResult | list[WriteResult]:
#     return get_deepl_client().rephrase_text(text=text, style=style, tone=tone)
