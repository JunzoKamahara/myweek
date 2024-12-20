from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import dateutil.relativedelta
import requests
import logging
import os

app = Flask(__name__)

user = os.environ.get('MYSQL_USER')     # ユーザ名
password = os.environ.get('MYSQL_PASSWORD') # パスワード
host = 'mysql_container'    # ホスト名 or IP
dbname = os.environ.get('MYSQL_DATABASE')       # データベース
port = 3306           # ポート
url = f'mysql+pymysql://{user}:{password}@{host}:{port}/{dbname}?charset=utf8'
print(url)
app.config['SQLALCHEMY_DATABASE_URI'] = url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# OpenWeatherMap設定
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY') 
DEFAULT_CITY = "Osaka"
WEATHER_CACHE = {}
CACHE_DURATION = timedelta(hours=1)  # キャッシュの有効期間

def get_weather_forecast():
    current_time = datetime.now()
    
    # キャッシュチェック
    if DEFAULT_CITY in WEATHER_CACHE:
        cached_data, cached_time = WEATHER_CACHE[DEFAULT_CITY]
        if current_time - cached_time < CACHE_DURATION:
            return cached_data

    # APIから天気情報を取得
    url = f"http://api.openweathermap.org/data/2.5/forecast?q={DEFAULT_CITY}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ja"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        daily_weather = {}
        for item in data['list']:
            # UTCからJSTに変換（+9時間）
            dt = datetime.fromtimestamp(item['dt']) + timedelta(hours=9)
            date = dt.strftime('%Y-%m-%d')
            hour = dt.strftime('%H:00')
            
            if date not in daily_weather:
                daily_weather[date] = {}
                
            daily_weather[date][hour] = {
                'temp': item['main']['temp'],
                'weather': item['weather'][0]['description'],
                'icon': item['weather'][0]['icon']
            }
        
        # キャッシュを更新
        WEATHER_CACHE[DEFAULT_CITY] = (daily_weather, current_time)
        return daily_weather
    
    return None

class ScheduleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    description = db.Column(db.Text)

@app.route('/')
@app.route('/<string:week_offset>')
def index(week_offset="0"):
    today = datetime.now().date()

    try: 
        week_offset = int(week_offset)
    except(Exception):
        week_offset = 0
    
    # 週のオフセットを考慮して開始日を計算
    start_of_week = today + timedelta(weeks=week_offset)
    end_of_week = start_of_week + timedelta(days=6)
    
    schedules = ScheduleItem.query.filter(
        ScheduleItem.date.between(start_of_week, end_of_week)
    ).order_by(ScheduleItem.date, ScheduleItem.start_time).all()
    
    # 曜日ごとにスケジュールを整理
    weekly_schedules = {
        (start_of_week + timedelta(days=i)).strftime('%Y-%m-%d'): [] 
        for i in range(7)
    }
    
    for schedule in schedules:
        weekly_schedules[schedule.date.strftime('%Y-%m-%d')].append(schedule)
    
    # 今週の日付だけ天気情報を取得
    weather_forecast = {}
    if week_offset == 0:
        weather_forecast = get_weather_forecast()
    
    return render_template('index.html', 
                         weekly_schedules=weekly_schedules, 
                         start_of_week=start_of_week,
                         week_offset=week_offset,
                         weather_forecast=weather_forecast)


@app.route('/add_schedule', methods=['GET', 'POST'])
def add_schedule():
    if request.method == 'POST':
        title = request.form['title']
        date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        start_time = datetime.strptime(request.form['start_time'], '%H:%M').time() if request.form['start_time'] else None
        end_time = datetime.strptime(request.form['end_time'], '%H:%M').time() if request.form['end_time'] else None
        description = request.form['description']
        
        new_schedule = ScheduleItem(
            title=title, 
            date=date, 
            start_time=start_time, 
            end_time=end_time, 
            description=description
        )
        
        db.session.add(new_schedule)
        db.session.commit()
        
        return redirect(url_for('index'))
    
    return render_template('add_schedule.html')

@app.route('/delete_schedule/<int:schedule_id>', methods=['POST'])
def delete_schedule(schedule_id):
    schedule = ScheduleItem.query.get_or_404(schedule_id)
    db.session.delete(schedule)
    db.session.commit()
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0")
