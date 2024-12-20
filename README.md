今日を起点として一週間のスケジュールを表示や書き込めるシンプルなスケジュールアプリです。

Docker環境で動作させることを想定しています。
.envファイルに以下の情報をセットして、パスワード等を設定する必要があります。

.env
```
MYSQL_USER=user
MYSQL_PASSWORD=password
MYSQL_DATABASE=weekly_schedule_db
MYSQL_ROOT_PASSWORD=root
OPENWEATHER_API_KEY=OpenWeatherMap APIのキー
```