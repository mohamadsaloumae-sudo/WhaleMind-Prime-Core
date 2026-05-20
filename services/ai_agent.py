import anthropic
from core.config import get_settings

# جلب الإعدادات (API Key والموديل) من ملف الإعدادات الخاص بكِ
settings = get_settings()
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

def get_ai_solution(error_log: str):
    """هذه الدالة ترسل الخطأ لكلاود وتجلب الحل البرمجي"""
    prompt = f"""
    أنت خبير في مشاريع الـ Python و الـ High-Frequency Trading.
    البوت الخاص بي (WhaleMind-Prime-Core) واجه الخطأ التالي:
    {error_log}
    
    قم بتحليل الخطأ واعطني الحل البرمجي أو التعديل المطلوب لملفات الكود فوراً وبشكل مختصر.
    """
    
    try:
        message = client.messages.create(
            model=settings.ai_model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    except Exception as e:
        return f"حدث خطأ أثناء الاتصال بـ Claude: {str(e)}"
