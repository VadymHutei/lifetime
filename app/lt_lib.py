import pymysql

import config


def getLanguages():
    connection = pymysql.connect(
        **config.db,
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with connection.cursor() as cursor:
            query = """
                SELECT
                    `code`,
                    `name`,
                    `default`
                FROM
                    `languages`
            """
            cursor.execute(query)
            result = cursor.fetchall()
    finally:
        connection.close()
    languages = {}
    default_language = None
    for lang in result:
        languages[lang['code']] = lang['name']
        if lang['default'] == 'Y':
            default_language = lang['code']
    return languages, default_language

def getTranlations():
    connection = pymysql.connect(
        **config.db,
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with connection.cursor() as cursor:
            query = """
                SELECT
                    `code`,
                    `lang`,
                    `translate`
                FROM
                    `translations`
            """
            cursor.execute(query)
            result = cursor.fetchall()
    finally:
        connection.close()
    translations = {}
    for t in result:
        code = t['code']
        lang = t['lang']
        translate = t['translate']
        if code not in translations:
            translations[code] = {}
        translations[code][lang] = translate
    return translations

def log(ip, url, method, time):
    connection = pymysql.connect(
        **config.db,
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with connection.cursor() as cursor:
            query = """
                INSERT
                    INTO `log`
                        (
                            `ip`,
                            `url`,
                            `method`,
                            `date`
                        )
                    VALUES
                        (%s, %s, %s, %s)
            """
            cursor.execute(
                query,
                (
                    ip,
                    url,
                    method,
                    time
                )
            )
        connection.commit()
    finally:
        connection.close()
