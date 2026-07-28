async def check_e5489_seats(parsed):
    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        try:
            train_info = TRAIN_TIMES.get(parsed["train_name"], TRAIN_TIMES["サンライズ出雲"])
            t_key = train_info["type_key"]
            dep_time = train_info["dep_time"]
            
            encoded_depart = ST_NAME_LIST_NO.get(parsed["dep"], '%93%8C%8B%9E')
            encoded_arrive = ST_NAME_LIST_NO.get(parsed["arr"], '%89%AA%8ER')
            facility_id = FACILITY_IDS[t_key]['未指定']
            
            date_str = parsed["date"].strftime("%Y%m%d")
            
            action = 'https://e5489.jr-odekake.net/e5489/cssp/CBDayTimeArriveSelRsvMyDiaSP?'
            param = (
                f"inputDepartStName={encoded_depart}"
                f"&inputArriveStName={encoded_arrive}"
                f"&inputType=0"
                f"&inputDate={date_str}"
                f"&inputHour={dep_time.split(':')[0]}"
                f"&inputMinute={dep_time.split(':')[1]}"
                f"&inputUniqueDepartSt=1"
                f"&inputUniqueArriveSt=1"
                f"&inputSearchType=1"
                f"&inputTransferDepartStName1={encoded_depart}"
                f"&inputTransferArriveStName1={encoded_arrive}"
                f"&inputTransferDepartStUnique1=1"
                f"&inputTransferArriveStUnique1=1"
                f"&inputTransferTrainType1=0001"
                f"&inputSpecificTrainType1=2"
                f"&inputSpecificBriefTrainKana1={facility_id}"
                f"&SequenceType=0"
            )
            target_url = action + param

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"]
                )
                page = await browser.new_page(
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
                )
                
                print(f"Navigating to: {target_url}")
                await page.goto(target_url, timeout=30000)
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(5)
                
                # デバッグ用にページのテキストの一部をログに出力
                body_text = await page.inner_text("body")
                print(f"--- PAGE TEXT SNIPPET --- \n{body_text[:300]}\n-------------------------")

                content = await page.content()
                await browser.close()

                seat_keywords = ["○", "△", "残席", "わずか", "残り", "空席"]
                found_keyword = next((kw for kw in seat_keywords if kw in content), None)

                if found_keyword:
                    return True, f"空席あり（検出キーワード: {found_keyword}）"
                else:
                    return False, "満席"

        except Exception as e:
            print(f"e5489 scraping error (attempt {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES - 1:
                return False, "エラーまたは満席"
            await asyncio.sleep(2)
            
    return False, "エラーまたは満席"
