from flask import Flask, request, jsonify
import hmac
import hashlib
import logging

app = Flask(__name__)

# Секретный ключ из настроек ЮКассы
YOOKASSA_SECRET_KEY = ''

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    # Получаем данные из запроса
    data = request.json
    signature = request.headers.get('Yookassa-Signature')

    # Проверяем подпись
    if not verify_signature(data, signature):
        logger.error("Неверная подпись запроса")
        return jsonify({"error": "Invalid signature"}), 400

    # Обрабатываем событие
    event_type = data['event']
    if event_type == 'payment.succeeded':
        payment_data = data['object']
        handle_payment_success(payment_data)
    elif event_type == 'payment.canceled':
        payment_data = data['object']
        handle_payment_canceled(payment_data)

    return jsonify({"status": "ok"}), 200

def verify_signature(data, signature):
    # Генерируем подпись
    message = f"{data['event']}.{data['object']['id']}"
    generated_signature = hmac.new(
        YOOKASSA_SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    # Сравниваем подписи
    return hmac.compare_digest(generated_signature, signature)

def handle_payment_success(payment_data):
    # Логика обработки успешного платежа
    user_id = payment_data['metadata'].get('user_id')  # Если вы передали user_id в метаданных
    amount = payment_data['amount']['value']
    currency = payment_data['amount']['currency']
    logger.info(f"Пользователь {user_id} успешно оплатил {amount} {currency}.")

def handle_payment_canceled(payment_data):
    # Логика обработки отмененного платежа
    user_id = payment_data['metadata'].get('user_id')
    logger.info(f"Платеж пользователя {user_id} отменен.")

if __name__ == '__main__':
    app.run(port=5000, ssl_context='adhoc')  # Запуск с самоподписанным SSL-сертификатом