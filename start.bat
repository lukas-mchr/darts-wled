PUSHD .
python "darts-wled.py" ^
-CON "127.0.0.1:8079" ^
-WEPS "your-primary-wled-ip" "your-secondary-wled-ip" ^
-DU "0" ^
-BSS "0.0" ^
-BRI "255" ^
-HFO "51" ^
-HF "x" ^
-IDE "solid|lightgoldenrodyellow" ^
-G "4" "87" "26" "29" "93" "42" "64" ^
-M "4" "87" "26" "29" "93" "42" "64" ^
-B "solid|red1" "1|red1" "ps|3|5" ^
-PJ "solid|green1" ^
-PL "solid|red1" ^
-S26 "84" ^
-S45 "Phased" ^
-S41 "Phased" ^
-S60 "13" ^
-S80 "29|blueviolet|yellow|yellow1" "rainbow|blue|yellow|yellow1" "13|aliceblue|yellow|yellow1" ^
-S100 "27" ^
-S120 "8" ^
-S140 "ps|3" ^
-S180 "78" "9" ^
-A1 "1-60" "ps|2" "solid|yellow1" ^
-A2 "16-30" "blink|green1" "rainbow|yellow1" "blink|peachpuff2" ^
-A3 "61-120" "29|blueviolet|s125|i145|red1|green1|p4"^
-BSW "1" 
-BSE "solid|red1" ^
-TE "solid|lightgoldenrodyellow" ^
-CE "solid|blue"