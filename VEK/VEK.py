import os
import json
import time
import random
from flask import Flask, render_template, jsonify, request

import os
app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))



from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSON

# Вставьте сюда ВАШУ длинную ссылку из Supabase (заменив [ваш_пароль] на реальный пароль)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres.ahdwufipqpkwdhwozzrp:MyVekGamePass123@aws-0-eu-west-1.pooler.supabase.com:6543/postgres'

db = SQLAlchemy(app)

class GameState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_data = db.Column(JSON, nullable=False)

with app.app_context():
    db.create_all()
    if not GameState.query.first():
        initial_data = {
            "clay": 0.0,
            "coins": 0.0,
            "current_tool": "Hands",
            "tool_durability": 0,
            "helpers": {
                "trainee": [],
                "foreman": []
            }
        }

        db.session.add(GameState(game_data=initial_data))
        db.session.commit()

DATA_FILE = 'game_data.json'

# Начальное состояние игры при первом запуске или сбросе
DEFAULT_DATA = {
    "clay": 0.0,
    "coins": 0.0,
    "current_tool": "Hands",  # Варианты: Hands, Shovel, Drill
    "tool_durability": 0,
    "helpers": {
        "trainee": [],  # Список временных меток окончания работы (timestamp)
        "foreman": []  # Список временных меток окончания работы (timestamp)
    }
}


def load_data():
    state = GameState.query.first()
    return state.game_data

def save_data(data):
    state = GameState.query.first()
    db.session.query(GameState).filter_by(id=state.id).update({"game_data": data})
    db.session.commit()



def update_idle_income(data):
    """Подсчет и начисление пассивного дохода от помощников с момента последнего запроса."""
    now = time.time()

    # Очищаем списки от тех помощников, чье время работы уже истекло
    data["helpers"]["trainee"] = [t for t in data["helpers"]["trainee"] if t > now]
    data["helpers"]["foreman"] = [t for t in data["helpers"]["foreman"] if t > now]

    # В этой версии игры доход рассчитывается динамически на фронтенде каждую секунду,
    # а бэкенд фиксирует только покупки и актуальный статус помощников.


@app.route('/')
def index():
    """Главная страница сайта."""
    return render_template('index.html')


@app.route('/api/state', methods=['GET'])
def get_state():
    """Получение текущего состояния игры."""
    data = load_data()
    update_idle_income(data)
    save_data(data)

    now = time.time()
    # Передаем на фронтенд количество оставшихся секунд для каждого помощника
    active_trainees = [max(0, int(t - now)) for t in data["helpers"]["trainee"]]
    active_foremen = [max(0, int(t - now)) for t in data["helpers"]["foreman"]]

    return jsonify({
        "clay": round(data["clay"], 1),
        "coins": int(data["coins"]),
        "current_tool": data["current_tool"],
        "tool_durability": data["tool_durability"],
        "trainees_left": active_trainees,
        "foremen_left": active_foremen
    })


@app.route('/api/dig', methods=['POST'])
def dig():
    """Логика клика по кнопке 'КОПАТЬ ЗЕМЛЮ!'."""
    data = load_data()
    update_idle_income(data)

    # Определяем силу копания базовую и износ
    power = 1
    if data["current_tool"] == "Shovel" and data["tool_durability"] > 0:
        power = 1 + 2
        data["tool_durability"] -= 1
    elif data["current_tool"] == "Drill" and data["tool_durability"] > 0:
        power = 1 + 5
        data["tool_durability"] -= 1

    # Проверяем сломался ли инструмент
    if data["current_tool"] != "Hands" and data["tool_durability"] <= 0:
        data["current_tool"] = "Hands"
        data["tool_durability"] = 0

    # Считаем критический удар (10% шанс)
    is_crit = random.random() < 0.10
    mined = power * 3 if is_crit else power

    data["clay"] += mined
    save_data(data)

    return jsonify({
        "status": "success",
        "mined": mined,
        "is_crit": is_crit
    })


@app.route('/api/sell', methods=['POST'])
def sell_clay():
    """Продажа всей глины на рынке по курсу 10 глины = 1 Кротокоин."""
    data = load_data()
    if data["clay"] >= 10:
        earned_coins = int(data["clay"] // 10)
        data["clay"] = data["clay"] % 10
        data["coins"] += earned_coins
        save_data(data)
        return jsonify({"status": "success", "earned": earned_coins})
    return jsonify({"status": "error", "message": "Недостаточно глины для продажи (нужно минимум 10)"})


@app.route('/api/buy', methods=['POST'])
def buy_item():
    """Покупка инструментов или наем помощников."""
    req_data = request.get_json() or {}
    item_type = req_data.get('item')

    data = load_data()
    now = time.time()

    prices = {
        "shovel": 5,
        "drill": 25,
        "trainee": 10,
        "foreman": 50
    }

    if item_type not in prices:
        return jsonify({"status": "error", "message": "Товар не найден"})

    price = prices[item_type]
    if data["coins"] < price:
        return jsonify({"status": "error", "message": "Недостаточно Кротокоинов!"})

    # Снимаем деньги
    data["coins"] -= price

    # Применяем покупку
    if item_type == "shovel":
        data["current_tool"] = "Shovel"
        data["tool_durability"] = 30
    elif item_type == "drill":
        data["current_tool"] = "Drill"
        data["tool_durability"] = 50
    elif item_type == "trainee":
        data["helpers"]["trainee"].append(now + 120)
    elif item_type == "foreman":
        data["helpers"]["foreman"].append(now + 180)

    save_data(data)
    return jsonify({"status": "success"})


@app.route('/api/tick', methods=['POST'])
def passive_tick():
    """Ежесекундное начисление пассивного дохода от фронтенд-таймера."""
    data = load_data()
    now = time.time()

    # Фильтруем только активных помощников
    active_trainees = [t for t in data["helpers"]["trainee"] if t > now]
    active_foremen = [t for t in data["helpers"]["foreman"] if t > now]

    # Считаем доход: +1 от стажера, +5 от бригадира
    income = len(active_trainees) * 1 + len(active_foremen) * 5

    data["clay"] += income
    data["helpers"]["trainee"] = active_trainees
    data["helpers"]["foreman"] = active_foremen

    save_data(data)
    return jsonify({"status": "success"})


@app.route('/api/reset', methods=['POST'])
def reset_game():
    """Полный сброс игрового прогресса."""
    save_data(DEFAULT_DATA.copy())
    return jsonify({"status": "success"})


if __name__ == '__main__':
    # host='0.0.0.0' открывает доступ для внешних подключений
    app.run(debug=True, host='0.0.0.0', port=10000)


