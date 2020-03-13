from datetime import date, datetime
import math

from flask import (
    Flask,
    render_template,
    request,
    abort,
    redirect,
    url_for
)
from dateutil.relativedelta import relativedelta
import pymysql
from functools import wraps

import config
import data

app = Flask(__name__)


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

def lang_redirect(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        language = kwargs.get('language', False)
        if language:
            if language not in languages:
                return redirect(url_for(f.__name__))
            if language == lang.default_language:
                return redirect(url_for(f.__name__))
        return f(*args, **kwargs)
    return decorated_function

languages, default_language = getLanguages()
translations = getTranlations()

@app.route('/', methods=['GET'])
@app.route('/<language>/', methods=['GET'])
@lang_redirect
def main(language=lang.default_language):
    params = {
        'countries': data.countries,
        'regions': data.regions,
        'world': data.world,
        'sex': data.sex
    }
    return render_template('main.html', **params)


@app.route('/result', methods=['GET'])
@app.route('/<language>/result', methods=['GET'])
@lang_redirect
def result(language=lang.default_language):
    birth_date = request.args.get('birth_date')
    if not birth_date:
        abort(400)
    birth_date = datetime.strptime(birth_date, '%Y-%m-%d').date()

    sex = request.args.get('sex', 'o')
    if not sex:
        sex = 'o'
    if sex not in data.sex:
        abort(400)

    country = request.args.get('country', 'World')
    if not country:
        country = 'World'
    if country == 'World':
        life_length_data = data.world
    elif country in data.countries:
        life_length_data = data.countries[country]
    elif country in data.regions:
        life_length_data = data.regions[country]
    else:
        abort(400)

    data_number = data.sex[sex][1]
    life_length_years = math.trunc(life_length_data[data_number])
    life_length_months = round(12 * math.modf(life_length_data[data_number])[0])
    life_length = relativedelta(
        years=life_length_years,
        months=life_length_months
    )

    today_date = date.today()

    death_date = birth_date + life_length

    lived = relativedelta(birth_date, today_date)

    life_left = relativedelta(death_date, today_date)

    params = {
        'life_left': life_left,
        'today_date': today_date.strftime('%d %b %Y'),
        'birth_date': birth_date.strftime('%d %b %Y'),
        'life_length': {
            'years': life_length_years,
            'months': life_length_months
        },
        'death_date': death_date.strftime('%d %b %Y'),
        'life_left': {
            'years': life_left.years,
            'months': life_left.months,
            'days': life_left.days
        },
        'sex': data.sex[sex][0],
        'country': country,
        'lived': {
            'years': abs(lived.years),
            'months': abs(lived.months)
        }
    }

    return render_template('result.html', **params)

@app.route('/<path:url>')
@app.route('/<string:url>')
def other(url=''):
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
                    request.remote_addr,
                    url,
                    request.method,
                    datetime.now()
                )
            )
        connection.commit()
    finally:
        connection.close()
    abort(400)
