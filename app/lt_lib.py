import math

import pymysql

import config

def getDateFormator(language=None):
    def dateFormate(**kwargs):
        if language is None:
            raise Exception('language is required')

        def getRule(language, type_):
            words = {
                'eng': {
                    'years': ('year', 'years', 'years'),
                    'months': ('month', 'months', 'months'),
                    'days': ('day', 'days', 'days'),
                },
                'rus': {
                    'years': ('год', 'года', 'лет'),
                    'months': ('месяц', 'месяца', 'месяцев'),
                    'days': ('день', 'дня', 'дней'),
                },
                'ukr': {
                    'years': ('рік', 'роки', 'років'),
                    'months': ('місяць', 'місяці', 'місяців'),
                    'days': ('день', 'дні', 'днів'),
                }
            }
            word = words[language][type_]
            def rule(items):
                if items in tuple(range(11, 15)):
                    return word[2]
                elif items % 10 == 1:
                    return word[0]
                elif items % 10 in tuple(range(2, 5)):
                    return word[1]
                else:
                    return word[2]
            return rule

        all_rules = {
            'eng': {
                'years': getRule('eng', 'years'),
                'months': getRule('eng', 'months'),
                'days': getRule('eng', 'days')
            },
            'rus': {
                'years': getRule('rus', 'years'),
                'months': getRule('rus', 'months'),
                'days': getRule('rus', 'days')
            },
            'ukr': {
                'years': getRule('ukr', 'years'),
                'months': getRule('ukr', 'months'),
                'days': getRule('ukr', 'days')
            }
        }
        all_rules['default'] = all_rules['eng']
        rules = all_rules[language] if language in all_rules else all_rules['default']
        result = []
        for item, rule in rules.items():
            value = kwargs.get(item)
            if value is None or value == 0:
                continue
            if not isinstance(value, int):
                raise Exception(f'wrong type of "{item}" parameter')
            result.append(f'{value} {rule(value)}')
        return ' '.join(result)
    return dateFormate

def decomposeDate(**kwargs):
    months_in_year = 12
    days_in_month = 31

    years = 0
    months = 0
    days = 0

    years_raw = kwargs.get('years')
    if years_raw:
        if isinstance(years_raw, int):
            years += years_raw
        if isinstance(years_raw, float):
            years += math.trunc(years_raw)
            months += round(months_in_year * math.modf(years_raw)[0])

    months_raw = kwargs.get('months')
    if months_raw:
        if isinstance(months_raw, int):
            months += months_raw
        if isinstance(months_raw, float):
            months += math.trunc(years_raw)
            days += round(days_in_month * math.modf(months_raw)[0])

    days_raw = kwargs.get('days')
    if days_raw:
        if isinstance(days_raw, int):
            days += days_raw
        if isinstance(days_raw, float):
            days += math.trunc(years_raw)

    if kwargs.get('normalize', False):
        if days > days_in_month:
            months += days // days_in_month
            days = days % days_in_month
        if months > months_in_year:
            years += months // months_in_year
            months = months % months_in_year

    return {
        'years': years,
        'months': months,
        'days': days
    }

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
                    `translation`
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
        translation = t['translation']
        if code not in translations:
            translations[code] = {}
        translations[code][lang] = translation
    return translations

def getCountries():
    connection = pymysql.connect(
        **config.db,
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with connection.cursor() as cursor:
            query = """
                SELECT
                    `c`.`id`,
                    `c`.`type`,
                    `c`.`alias`,
                    `ct`.`lang`,
                    `ct`.`name`,
                    `ct`.`locative`
                FROM
                    `countries` AS `c`
                INNER JOIN
                    `countries_text` AS `ct`
                    ON
                        `ct`.`country_id` = `c`.`id`
                ORDER BY `ct`.`name` ASC
            """
            cursor.execute(query)
            result = cursor.fetchall()
    finally:
        connection.close()
    countries = {}
    for row in result:
        if row['id'] not in countries:
            countries[row['id']] = {
                'id': row['id'],
                'type': row['type'],
                'alias': row['alias'],
                'name': {},
                'locative': {},
                'life_exp': {}
            }
        countries[row['id']]['name'][row['lang']] = row['name']
        countries[row['id']]['locative'][row['lang']] = row['locative']
    connection = pymysql.connect(
        **config.db,
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with connection.cursor() as cursor:
            query = """
                SELECT
                    `c`.`id`,
                    `l`.`gender_id`,
                    `l`.`life_exp`
                FROM
                    `countries` AS `c`
                INNER JOIN
                    `life_exp` AS `l`
                    ON
                        `l`.`country_id` = `c`.`id`
            """
            cursor.execute(query)
            result = cursor.fetchall()
    finally:
        connection.close()
    for row in result:
        countries[row['id']]['life_exp'][row['gender_id']] = row['life_exp']
    return countries

def getCountryAlias(name):
    allowed_chars_range = []
    digits_range = range(ord('0'), ord('9') + 1)
    letters_range = range(ord('a'), ord('z') + 1)
    allowed_chars_range += list(digits_range)
    allowed_chars_range += list(letters_range)
    allowed_chars_range.append(ord('-'))
    allowed_chars_range.append(ord('_'))
    allowed_chars = [chr(x) for x in allowed_chars_range]
    l_name = list(name.lower().replace(' ', '-'))
    return ''.join(filter(lambda x: x in allowed_chars, l_name)).strip('-_')

def getGenders():
    connection = pymysql.connect(
        **config.db,
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with connection.cursor() as cursor:
            query = """
                SELECT
                    `g`.`id`,
                    `gt`.`lang`,
                    `gt`.`name`
                FROM
                    `genders` AS `g`
                INNER JOIN
                    `genders_text` AS `gt`
                    ON
                        `gt`.`gender_id` = `g`.`id`
            """
            cursor.execute(query)
            result = cursor.fetchall()
    finally:
        connection.close()
    genders = {}
    for row in result:
        if row['id'] not in genders:
            genders[row['id']] = {}
        genders[row['id']][row['lang']] = {'name': row['name']}
    return genders

def getTranslator(translations, language):
    def translate(code):
        return translations[code].get(language, code) if code in translations else code
    return translate

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

def setTranslations(code, translations):
    connection = pymysql.connect(
        **config.db,
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with connection.cursor() as cursor:
            for language, translation in translations.items():
                query = """
                    INSERT
                    INTO `translations`
                        (
                            `code`,
                            `lang`,
                            `translation`
                        )
                    VALUES
                        (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        `translation` = %s
                """
                cursor.execute(
                    query,
                    (
                        code,
                        language,
                        translation,
                        translation
                    )
                )
                connection.commit()
    finally:
        connection.close()

def updateTranslations(code, translations):
    connection = pymysql.connect(
        **config.db,
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with connection.cursor() as cursor:
            for language, translation in translations.items():
                query = """
                    UPDATE `translations`
                    SET
                        `translation` = %s
                    WHERE
                        `code` = %s
                    AND
                        `lang` = %s
                """
                cursor.execute(
                    query,
                    (
                        translation,
                        code,
                        language
                    )
                )
                connection.commit()
    finally:
        connection.close()

def deleteTranslation(code):
    connection = pymysql.connect(
        **config.db,
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with connection.cursor() as cursor:
            query = """
                DELETE
                FROM `translations`
                WHERE
                    `code` = %s
            """
            cursor.execute(query, (code,))
        connection.commit()
    finally:
        connection.close()
