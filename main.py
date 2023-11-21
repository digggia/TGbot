import psycopg2
import configparser
import telebot
from telebot import types, TeleBot
from telebot.storage import StateMemoryStorage
from telebot.handler_backends import State, StatesGroup
import random

config = configparser.ConfigParser()
config.read('config.ini')

state_storage = StateMemoryStorage()
TG_TOKEN = config['TG']['TOKEN']
bot = TeleBot(TG_TOKEN, state_storage=state_storage)
known_users = []
userStep = {}

class Command:
    ADD_WORD = 'Добавить слово ➕'
    DELETE_WORD = 'Удалить слово🔙'
    NEXT = 'Дальше ⏭'
    START_OVER = 'Начать заново'

class MyStates(StatesGroup):
    target_word = State()
    translate_word = State()
    another_words = State()
    add_words = State()
    del_words = State()
def connect_to_db():
    try:
        conn = psycopg2.connect(
            dbname=config['database']['DB_NAME'],
            user=config['database']['DB_USER'],
            password=config['database']['DB_PASSWORD'],
            host=config['database']['DB_HOST'],
            port=config['database']['DB_PORT']
        )
        return conn
    except Exception as e:
        print(f"Ошибка при подключении к базе данных: {e}")
        return None
def create_tables():
    with connect_to_db() as conn:
        if conn:
            with conn.cursor() as cursor:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS words (
                        id SERIAL PRIMARY KEY,
                        target_word TEXT NOT NULL,
                        translate_word TEXT NOT NULL,
                        example_usage TEXT,
                        owner_id BIGINT,
                        UNIQUE (target_word, translate_word)
                    )
                ''')
                examples = [
                    ('Мир', 'World', 'Peace in the world is everything.'),
                    ('Любовь', 'Love', 'Love for knowledge inspires.'),
                    ('Дружба', 'Friendship', 'Friendship is a treasure.'),
                    ('Природа', 'Nature', 'Nature inspires creativity.'),
                    ('Приключение', 'Adventure', 'Adventures broaden horizons.'),
                    ('Успех', 'Success', 'Success is the result of hard work and perseverance.'),
                    ('Испытание', 'Challenge', 'Challenges make us stronger.'),
                    ('Мечта', 'Dream', 'Dreams become bright realities.'),
                    ('Смелость', 'Courage', 'Courage is the key to new opportunities.'),
                    ('Знание', 'Knowledge', 'Knowledge is power and freedom.'),
                ]

                for example in examples:
                    cursor.execute('''
                                SELECT id FROM words WHERE target_word = %s AND translate_word = %s
                            ''', (example[0], example[1]))

                    existing_word = cursor.fetchone()

                    if not existing_word:
                        cursor.execute('''
                                    INSERT INTO words (target_word, translate_word, example_usage)
                                    VALUES (%s, %s, %s)
                                ''', example)

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        word_id BIGINT,
                        FOREIGN KEY (word_id) REFERENCES words(id)
                    )
                ''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS guessed_words (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        word_id BIGINT,
                        FOREIGN KEY (word_id) REFERENCES words(id),
                        UNIQUE (user_id, word_id)
                    )
                ''')

            conn.commit()
        else:
            print(f"Не удалось подключиться к базе данных")

def get_random_words(exclude_word, count=3):
    with connect_to_db() as conn:
        if conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT translate_word FROM words WHERE target_word != %s ORDER BY RANDOM() LIMIT %s",
                               (exclude_word, count))
                words = cursor.fetchall()
                return [word[0] for word in words]
    return []

@bot.message_handler(commands=['cards', 'start'])
def create_cards(message):
    cid = message.chat.id
    user_id = message.from_user.id
    clear_guessed_words(user_id)

    user_info = bot.get_chat(user_id)
    first_name = user_info.first_name
    welcome_message = f"Привет, {first_name}! Давай начнем изучение слов. Вот первое слово для тебя:"
    bot.send_message(cid, welcome_message)

    with connect_to_db() as conn:
        if conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                        SELECT w.target_word, w.translate_word, w.example_usage, w.id
                        FROM words w
                        LEFT JOIN guessed_words g ON w.id = g.word_id AND g.user_id = %s
                        LEFT JOIN users u ON w.id = u.word_id AND u.user_id = %s
                        WHERE (w.owner_id IS NULL OR w.owner_id = %s OR u.id IS NOT NULL) AND g.id IS NULL
                        ORDER BY RANDOM() LIMIT 1
                    """, (user_id, user_id, user_id))
                word_data = cursor.fetchone()

                if word_data:
                    target_word, translate, example_usage, new_word_id = word_data
                    others = get_random_words(target_word, count=3)
                    random.shuffle(others)
                    options = [translate] + others

                    cursor.execute("SELECT id FROM users WHERE user_id = %s AND word_id = %s", (user_id, new_word_id))
                    existing_user = cursor.fetchone()

                    if not existing_user:
                        cursor.execute("INSERT INTO users (user_id, word_id) VALUES (%s, %s) RETURNING id",(user_id, new_word_id))
                        conn.commit()
                else:
                    target_word = 'Дружба'
                    translate = 'Friendship'
                    options = ['Мир', 'Здравствуйте', 'Дружба', 'Белый']

    if cid not in known_users:
        known_users.append(cid)
        userStep[cid] = 0

    markup, greeting = create_keyboard_markup(target_word, translate, others)
    bot.send_message(cid, greeting, reply_markup=markup)
    bot.set_state(user_id, MyStates.target_word, cid)
    bot.register_next_step_handler(message, message_reply)

    with bot.retrieve_data(user_id, cid) as data:
        data['target_word'] = target_word
        data['translate_word'] = translate
        data['example_usage'] = example_usage
        data['other_words'] = options
        data['word_id'] = new_word_id
        data['user_id'] = user_id
@bot.message_handler(func=lambda message: True, content_types=['text'])
def message_reply(message):
    cid = message.chat.id
    user_id = message.from_user.id

    with bot.retrieve_data(user_id, cid) as data:
        if message.text == 'Начать заново':
            create_cards(message)
            return
        if message.text == 'Добавить слово ➕':
            add_word(message)
            return
        if message.text == 'Удалить слово🔙':
            del_word(message)
            return
        if message.text == 'Дальше ⏭':
            next_cards(message)
            return

        if message.text == data['translate_word']:
            if data['example_usage'] != None:
                bot.send_message(cid, f"Правильно!\n{data['example_usage']}")
                data['attempts_left'] = 2
            else:
                bot.send_message(cid, f"Правильно!\nПример использования отсутствует.")
                data['attempts_left'] = 2

            add_guessed_word(user_id, data['word_id'])
        else:
            if 'attempts_left' not in data:
                data['attempts_left'] = 2

            if data['attempts_left'] > 0:
                data['attempts_left'] -= 1
                bot.send_message(cid,f"Неправильно, у вас осталось {data['attempts_left'] + 1} попыток. Попробуйте еще раз.")
                return
            else:
                bot.send_message(cid,f"Неправильно, у вас закончились попытки.\nПравильное слово: {data['translate_word']}")
                data['attempts_left'] = 2

    next_cards(message)

def next_cards(message):
    cid = message.chat.id
    user_id = message.from_user.id

    with connect_to_db() as conn:
        if conn:
            with conn.cursor() as cursor:

                cursor.execute("SELECT word_id FROM guessed_words WHERE user_id = %s", (user_id,))
                guessed_words = cursor.fetchall()
                guessed_words = [str(word[0]) for word in guessed_words]

                placeholders_guessed = ', '.join(['%s'] * len(guessed_words))

                all_words = list(map(int, guessed_words))

                cursor.execute(f"""
                                    SELECT target_word, translate_word, example_usage, id 
                                    FROM words 
                                    WHERE (owner_id IS NULL OR owner_id = %s) 
                                        AND id NOT IN ({placeholders_guessed or 'NULL'}) 
                                    ORDER BY RANDOM() 
                                    LIMIT 1
                                    """,
                    tuple([user_id] + all_words)
                )
                word_data = cursor.fetchone()

                if not word_data:
                    markup = types.ReplyKeyboardMarkup(row_width=1)
                    start_over_button = create_start_over_button()
                    markup.add(start_over_button)
                    greeting = "Все слова отгаданы! Начнем заново?"
                    bot.send_message(message.chat.id, greeting, reply_markup=markup)
                    return
                else:
                    target_word, translate, example_usage, word_id = word_data
                    others = get_random_words(target_word, count=3)
                    random.shuffle(others)
                    options = [translate] + others

                cursor.execute("SELECT id FROM users WHERE user_id = %s AND word_id = %s", (user_id, word_id))
                existing_user = cursor.fetchone()

                if not existing_user:
                    cursor.execute("INSERT INTO users (user_id, word_id) VALUES (%s, %s) RETURNING id",(user_id, word_id))
                    conn.commit()

                with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
                    data['target_word'] = target_word
                    data['translate_word'] = translate
                    data['example_usage'] = example_usage
                    data['other_words'] = options
                    data['word_id'] = word_id
                    data['user_id'] = user_id
                    data.pop('attempts_left', None)

                markup, greeting = create_keyboard_markup(target_word, translate, others)
                bot.send_message(message.chat.id, greeting, reply_markup=markup)
                bot.set_state(message.from_user.id, MyStates.target_word, message.chat.id)

def add_guessed_word(user_id, word_id):
    with connect_to_db() as conn:
        if conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM guessed_words WHERE user_id = %s AND word_id = %s", (user_id, word_id))
                existing_record = cursor.fetchone()

                if not existing_record:
                    cursor.execute("INSERT INTO guessed_words (user_id, word_id) VALUES (%s, %s)", (user_id, word_id))
                    conn.commit()
        else:
            print("Не удалось подключиться к базе данных")
def create_start_over_button():
    start_over_button = types.KeyboardButton(Command.START_OVER)
    return start_over_button

def create_keyboard_markup(target_word, translate, others):
    markup = types.ReplyKeyboardMarkup(row_width=2)
    target_word_btn = types.KeyboardButton(translate)
    buttons = [target_word_btn] + [types.KeyboardButton(word) for word in others]
    random.shuffle(buttons)
    next_btn = types.KeyboardButton(Command.NEXT)
    add_word_btn = types.KeyboardButton(Command.ADD_WORD)
    delete_word_btn = types.KeyboardButton(Command.DELETE_WORD)
    buttons.extend([next_btn, add_word_btn, delete_word_btn])
    markup.add(*buttons)

    greeting = f"Выбери перевод слова:\n🇷🇺 {target_word}\n"

    return markup, greeting

def clear_guessed_words(user_id):
    with connect_to_db() as conn:
        if conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM guessed_words WHERE user_id = %s", (user_id,))
                conn.commit()
        else:
            print("Не удалось подключиться к базе данных")
    userStep[user_id] = 0


@bot.message_handler(func=lambda message: message.text == Command.ADD_WORD)
def add_word(message):
    cid = message.chat.id
    user_id = message.from_user.id
    userStep[cid] = 1
    bot.set_state(user_id, MyStates.add_words, cid)
    bot.send_message(cid, "Введите слово на русском, которое вы хотите добавить в словарь:")
    bot.register_next_step_handler(message, get_added_word)

def get_added_word(message):
    cid = message.chat.id
    user_id = message.from_user.id
    bot.set_state(user_id, MyStates.add_words, cid)

    target_word = message.text

    bot.send_message(message.chat.id, f"Вы ввели слово: {target_word}")
    bot.send_message(message.chat.id, "Теперь введите перевод этого слова на английский:")
    bot.register_next_step_handler(message, save_word_to_db, user_id, target_word)

def save_word_to_db(message, user_id, target_word):
    translation = message.text

    with connect_to_db() as conn:
        if conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id FROM words WHERE LOWER(target_word) = %s AND LOWER(translate_word) = %s",(target_word.lower(), translation.lower()))
                existing_record = cursor.fetchone()

                if not existing_record:
                    cursor.execute("INSERT INTO words (target_word, translate_word, owner_id) VALUES (%s, %s, %s) RETURNING id",(target_word, translation, user_id))
                    word_id = cursor.fetchone()[0]
                    cursor.execute("INSERT INTO users (user_id, word_id) VALUES (%s, %s) RETURNING id",(user_id, word_id))
                    conn.commit()

                    cursor.execute("SELECT COUNT(*) FROM users WHERE user_id = %s", (user_id,))
                    word_count = cursor.fetchone()[0]

                    bot.send_message(user_id, f"Ваше слово записано, Вы изучаете уже {word_count} слов")
                    bot.set_state(user_id, MyStates.target_word, user_id)
                    next_cards(message)
                else:
                    bot.send_message(user_id, "Это слово уже есть в вашем словаре.")
                    bot.set_state(user_id, MyStates.target_word, user_id)
                    next_cards(message)
        else:
            print("Не удалось подключиться к базе данных")


@bot.message_handler(func=lambda message: message.text == Command.DELETE_WORD)
def del_word(message):
    cid = message.chat.id
    user_id = message.from_user.id
    userStep[cid] = 1
    bot.set_state(user_id, MyStates.del_words, cid)
    bot.send_message(cid, "Введите слово на английском, которое вы хотите удалить")
    bot.register_next_step_handler(message, get_del_word)

def get_del_word(message):
    cid = message.chat.id
    user_id = message.from_user.id
    bot.set_state(user_id, MyStates.del_words, cid)
    target_word = message.text.lower()

    with connect_to_db() as conn:
        if conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT w.id 
                    FROM words w
                    LEFT JOIN users u ON w.id = u.word_id
                    WHERE LOWER(w.translate_word) = %s AND u.user_id = %s
                """, (target_word, user_id))

                word_id = cursor.fetchone()

                if word_id:
                    word_id = word_id[0]
                    cursor.execute("DELETE FROM users WHERE user_id = %s AND word_id = %s", (user_id, word_id))
                    cursor.execute("DELETE FROM guessed_words WHERE user_id = %s AND word_id = %s", (user_id, word_id))
                    cursor.execute("DELETE FROM words WHERE id = %s", (word_id,))
                    conn.commit()

                    cursor.execute("SELECT COUNT(*) FROM users WHERE user_id = %s", (user_id,))
                    word_count = cursor.fetchone()[0]

                    bot.send_message(user_id, f"Ваше слово '{target_word}' было удалено. Вы изучаете уже {word_count} слов.")
                    bot.set_state(user_id, MyStates.target_word, cid)
                    next_cards(message)
                else:
                    bot.send_message(user_id, f"Слово '{target_word}' не найдено в вашем словаре.")
                    bot.set_state(user_id, MyStates.target_word, cid)
                    next_cards(message)
        else:
            print("Не удалось подключиться к базе данных")


if __name__ == '__main__':
    create_tables()
    bot.infinity_polling(skip_pending=True)

