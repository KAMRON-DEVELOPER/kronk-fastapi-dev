import aiohttp
from settings.my_config import get_settings


class ZeptoMail:
    API_URL = "https://api.zeptomail.com/v1.1/email/template"
    HEADERS = {"accept": "application/json", "content-type": "application/json", "authorization": f"Zoho-enczapikey {get_settings().EMAIL_SERVICE_API_KEY}"}

    @staticmethod
    async def send_email(to_email: str, username: str, code: str = "0000", for_reset_password: bool = False, for_thanks_signing_up: bool = False):
        payload = {
            "template_alias": "kronk-verification-key-alias",
            "from": {"address": "verify@kronk.uz", "name": "verify"},
            "to": [{"email_address": {"name": username, "address": to_email}}],
            "merge_info": {"code": code, "username": username},
        }
        if for_reset_password:
            payload.update({"template_alias": "kronk-password-reset-key-alias", "from": {"address": "reset@kronk.uz", "name": "reset"}})
        if for_thanks_signing_up:
            payload.update({"template_alias": "kronk-thanks-for-signing-up-key-alias", "from": {"address": "thanks@kronk.uz", "name": "thanks"}})

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url=ZeptoMail.API_URL, json=payload, headers=ZeptoMail.HEADERS) as response:
                    return {"status": response.status, "message": (await response.json())["message"]}
            except Exception as e:
                print(f"🌋 Exception in ZeptoMail send_email: {e}")
                return {"status": "🌋"}
