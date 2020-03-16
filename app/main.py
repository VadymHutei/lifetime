from datetime import date, datetime
import math
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    abort,
    redirect,
    url_for
)
from dateutil.relativedelta import relativedelta

import config
import data
import lt_lib

def foo():
    return 'bar'


app = Flask(__name__)

languages, default_language = lt_lib.getLanguages()
translations = lt_lib.getTranlations()
countries = lt_lib.getCountries()
genders = lt_lib.getGenders()


def lang_redirect(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        language = kwargs.get('language', False)
        if language:
            if language not in languages:
                return redirect(url_for(f.__name__, **request.args))
            if language == default_language:
                return redirect(url_for(f.__name__, **request.args))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/translations', methods=['GET'])
def translations_page():
    admin_key = request.args.get('admin_key')
    if admin_key != config.admin_key:
        abort(400)
    params = {
        'admin_key': admin_key,
        'languages': languages,
        'translations': translations
    }
    return render_template('translations.html', **params)

@app.route('/translations/add', methods=['GET', 'POST'])
def translations_add():
    admin_key = request.args.get('admin_key')
    if admin_key != config.admin_key:
        abort(400)
    global translations
    if request.method == 'GET':
        params = {
            'admin_key': admin_key,
            'languages': languages
        }
        return render_template('translations_add.html', **params)
    if request.method == 'POST':
        code = request.form['code']
        translations = {}
        for name, translation in request.form.items():
            if name[:9] == 'translate':
                language = name[10:13]
                if language not in languages:
                    continue
                translations[language] = translation
        lt_lib.setTranslations(code, translations)
        translations = lt_lib.getTranlations()
        return redirect(url_for('translations_page', admin_key=config.admin_key))

@app.route('/translations/edit', methods=['GET', 'POST'])
def translations_edit():
    admin_key = request.args.get('admin_key')
    if admin_key != config.admin_key:
        abort(400)
    global translations
    if request.method == 'GET':
        code = request.args.get('code')
        params = {
            'admin_key': admin_key,
            'languages': languages,
            'code': code,
            'translations': translations[code]
        }
        return render_template('translations_edit.html', **params)
    if request.method == 'POST':
        code = request.form['code']
        trans = {}
        for name, translation in request.form.items():
            if name[:9] == 'translate':
                language = name[10:13]
                if language not in languages:
                    continue
                trans[language] = translation
        lt_lib.setTranslations(code, trans)
        translations = lt_lib.getTranlations()
        return redirect(url_for('translations_page', admin_key=config.admin_key))

@app.route('/translations/delete', methods=['GET'])
def translations_delete():
    admin_key = request.args.get('admin_key')
    if admin_key != config.admin_key:
        abort(400)
    code = request.args.get('code')
    lt_lib.deleteTranslation(code)
    global translations
    translations = lt_lib.getTranlations()
    return redirect(url_for('translations_page', admin_key=config.admin_key))

@app.route('/', methods=['GET'])
@app.route('/<language>', methods=['GET'])
@lang_redirect
def main(language=default_language):
    params = {
        'translate': lt_lib.getTranslator(translations, language),
        'language': language,
        'translations': {t: v.get(language) for t, v in translations.items()},
        'countries': countries,
        'world': countries[181],
        'genders': genders
    }
    return render_template('main.html', **params)


@app.route('/result', methods=['GET'])
@app.route('/<language>/result', methods=['GET'])
@lang_redirect
def result(language=default_language):
    birth_date = request.args.get('birth_date')
    if not birth_date:
        abort(400)
    birth_date = datetime.strptime(birth_date, '%Y-%m-%d').date()

    gender = int(request.args.get('sex', '1'))
    if gender not in genders:
        abort(400)

    country_id = int(request.args.get('country', '181'))
    if country_id not in countries:
        abort(400)
    country = countries.get(country_id)['name'][language]
    life_exp = countries.get(country_id)['life_exp']

    life_length_years = math.trunc(life_exp[gender])
    life_length_months = round(12 * math.modf(life_exp[gender])[0])
    life_length = relativedelta(
        years=life_length_years,
        months=life_length_months
    )

    today_date = date.today()

    death_date = birth_date + life_length

    lived = relativedelta(birth_date, today_date)

    life_left = relativedelta(death_date, today_date)

    params = {
        'translate': lt_lib.getTranslator(translations, language),
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
        'sex': genders[gender][language]['name'],
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
    lt_lib.log(
        request.remote_addr,
        url,
        request.method,
        datetime.now()
    )
    abort(400)
