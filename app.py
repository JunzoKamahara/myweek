from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import NoResultFound
from flask_login import UserMixin, LoginManager, login_required, login_user, logout_user, current_user
from flask_dance.contrib.github import make_github_blueprint, github
from flask_dance.consumer import oauth_authorized, oauth_error
from flask_dance.consumer.storage.sqla import OAuthConsumerMixin, SQLAlchemyStorage
from datetime import datetime, timedelta
import dateutil.relativedelta
import requests
import logging
import os
from dotenv import load_dotenv

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev')

load_dotenv()

user = os.getenv('MYSQL_USER')     # ユーザ名
password = os.getenv('MYSQL_PASSWORD') # パスワード
host = 'mysql_container'    # ホスト名 or IP
dbname = os.getenv('MYSQL_DATABASE')       # データベース
port = 3306           # ポート
url = f'mysql+pymysql://{user}:{password}@{host}:{port}/{dbname}?charset=utf8'
app.config['SQLALCHEMY_DATABASE_URI'] = url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    github_id = db.Column(db.Integer, unique=True)
    avatar_url = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ScheduleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    description = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # 追加
    user = db.relationship('User', backref=db.backref('schedules', lazy=True))  # 追加

# OAuth用のモデル
class OAuth(OAuthConsumerMixin, db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey(User.id))
    user = db.relationship(User)

# OpenWeatherMap設定
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY') 
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

# GitHub OAuth設定 追加
app.config['GITHUB_OAUTH_CLIENT_ID'] = os.getenv('GITHUB_CLIENT_ID')
app.config['GITHUB_OAUTH_CLIENT_SECRET'] = os.getenv('GITHUB_CLIENT_SECRET')

github_bp = make_github_blueprint(
    storage=SQLAlchemyStorage(
        OAuth,
        db.session,
        user=current_user,
        user_required=False  # これが重要
    )
)
# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'github.login'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# oauth_authorizedシグナルハンドラを追加
@oauth_authorized.connect_via(github_bp)
def github_logged_in(blueprint, token):
    if not token:
        flash("Failed to log in with GitHub.", category="error")
        return False

    resp = blueprint.session.get("/user")
    if not resp.ok:
        flash("Failed to fetch user info from GitHub.", category="error")
        return False

    github_info = resp.json()
    github_user_id = str(github_info["id"])

    # ユーザーが存在するか確認
    query = User.query.filter_by(github_id=github_user_id)
    try:
        user = query.one()
    except NoResultFound:
        # 新規ユーザーを作成
        user = User(
            username=github_info["login"],
            github_id=github_user_id,
            avatar_url=github_info["avatar_url"]
        )
        db.session.add(user)
        db.session.commit()

    # ユーザーをログイン状態にする
    login_user(user)

    # Falseを返すことで、Flask-Danceに自動的なトークン保存をさせない
    return False

# notify on OAuth provider error
@oauth_error.connect_via(github_bp)
def github_error(blueprint, message, response):
    msg = ("OAuth error from {name}! " "message={message} response={response}").format(
        name=blueprint.name, message=message, response=response
    )
    flash(msg, category="error")

@app.route('/login')
def login():
    if not github.authorized:
        return redirect(url_for('github.login')) # github.loginでログイン
    return redirect(url_for('index')) #認証されていればindexにジャンプ

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

app.register_blueprint(github_bp, url_prefix='/login')

@app.route('/')
@app.route('/<string:week_offset>')
@login_required
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
        ScheduleItem.date.between(start_of_week, end_of_week),
        ScheduleItem.user_id == current_user.id  # ユーザーのスケジュールのみ取得
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
@login_required
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
            description=description,
            user_id=current_user.id  # ユーザーIDを追加
        )
        
        db.session.add(new_schedule)
        db.session.commit()
        
        return redirect(url_for('index'))
    
    return render_template('add_schedule.html')

@app.route('/delete_schedule/<int:schedule_id>', methods=['POST'])
@login_required
def delete_schedule(schedule_id):
    schedule = ScheduleItem.query.filter_by(
        id=schedule_id,
        user_id=current_user.id  # 現在のユーザーの予定のみ削除可能
    ).first_or_404()
    db.session.delete(schedule)
    db.session.commit()
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0")
