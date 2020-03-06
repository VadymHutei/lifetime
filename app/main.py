from flask import Flask, render_template, request, abort
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

import data

app = Flask(__name__)


@app.route('/', methods=['GET'])
def main():
    params = {
        'countries': data.countries,
        'regions': data.regions,
        'world': data.world
    }
    return render_template('main.html', **params)


@app.route('/result', methods=['GET'])
def result():
    life_lengths = {
        'm': relativedelta(years=66, months=4),
        'f': relativedelta(years=76, months=2)
    }

    birth_date = request.args.get('birth_date')
    if birth_date is None:
        abort(400)

    sex = request.args.get('sex')
    if sex not in life_lengths:
        abort(400)

    birth_date = datetime.strptime(birth_date, '%Y-%m-%d').date()
    life_length = life_lengths[sex]
    death_date = birth_date + life_length
    today_date = date.today()
    life_left = relativedelta(death_date, today_date)

    params = {
        'life_left': life_left,
        'today_date': today_date,
        'birth_date': birth_date,
        'life_length': life_length,
        'death_date': death_date,
        'years_left': life_left.years,
        'months_left': life_left.months,
        'days_left': life_left.days
    }

    return render_template('result.html', **params)
