import asyncio
import uvicorn
import json
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright

app = FastAPI()
shared_page = None 
data_queue = asyncio.Queue()
is_processing = False
has_error = False

# Quản lý kết nối để gửi tín hiệu đổi màu
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except: pass

manager = ConnectionManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

async def fill_select2(page, container_selector, search_text):
    await page.wait_for_selector(container_selector, state="visible", timeout=5000)
    await page.click(container_selector)
    search_input = ".select2-container--open input.select2-search__field"
    await page.wait_for_selector(search_input, state="visible", timeout=3000)
    await page.fill(search_input, search_text)
    await asyncio.sleep(0.5) 
    result_xpath = f"//li[contains(@class, 'select2-results__option') and (normalize-space(text())='{search_text}' or contains(.,'{search_text}'))]"
    await page.wait_for_selector(result_xpath, state="visible", timeout=3000)
    await page.click(result_xpath)
    try:
        await page.wait_for_selector(".select2-container--open", state="hidden", timeout=2000)
    except:
        await page.keyboard.press("Escape")
    print(f"   [+] Đã chọn Select2: {search_text}")

async def select_dropdown_human(page, selector, label_text):
    try:
        print(f"   [+] Đang chọn: {label_text}")
        await page.wait_for_selector(f"{selector}:not([disabled])", timeout=15000)
        await page.select_option(selector, label=label_text)
        await page.dispatch_event(selector, "change")
        await asyncio.sleep(2) 
    except Exception as e:
        print(f"   [!] Lỗi khi chọn {label_text}: {e}")

async def auto_fill_location_and_open_form():
    global shared_page
    try:
        print("\n[BƯỚC 1] Thiết lập Cơ sở lưu trú...")
        await select_dropdown_human(shared_page, "select#accomStay_cboPROVINCE_ID", "Thành phố Cần Thơ")
        await select_dropdown_human(shared_page, "select#accomStay_cboADDRESS_ID", "Phường Long Tuyền")
        await select_dropdown_human(shared_page, "select#accomStay_cboACCOMMODATION_TYPE", "Nhà ngăn phòng cho thuê")
        await select_dropdown_human(shared_page, "select#accomStay_cboNAME", "NHÀ TRỌ TÂM AN 2")
        print("[BƯỚC 2] Mở form thêm người...")
        btn_add = "a#btnAddPersonLT" 
        await shared_page.wait_for_selector(btn_add, state="visible")
        await shared_page.click(btn_add)
        await shared_page.wait_for_selector("#addpersonLT", state="visible", timeout=10000)
        await asyncio.sleep(1)
        print("[OK] Sẵn sàng nhận dữ liệu khách.")
    except Exception as e:
        print(f"[LỖI] Thiết lập thất bại: {e}")

async def fill_guest_data(task_item):
    global shared_page, has_error
    data = task_item['data']
    idx = task_item['index']
    if not shared_page: return
    try:
        # Gửi tín hiệu đang xử lý dòng này
        await manager.broadcast({"type": "PROCESSING", "index": idx})
        
        print(f"\n--- Đang nhập liệu cho: {data.get('ho_ten')} ---")
        await shared_page.fill("input#guest_txtCITIZENNAME", data.get('ho_ten', '').upper())
        await shared_page.fill("input#guest_txtIDCARD_NUMBER", data.get('cccd', ''))

        dob = data.get('ngay_birth', data.get('ngay_sinh', ''))
        if dob:
            await shared_page.evaluate(f"""
                (dateVal) => {{
                    const el = document.getElementById('guest_txtDOB');
                    el.value = dateVal;
                    if (window.jQuery && jQuery(el).data('datepicker')) {{ jQuery(el).datepicker('update', dateVal); }}
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    el.blur();
                }}
            """, dob)

        await fill_select2(shared_page, "#select2-guest_cboGENDER_ID-container", data.get('gioi_tinh', ''))
        await fill_select2(shared_page, "#select2-guest_cboCOUNTRY-container", data.get('quoc_gia', 'Cộng hòa xã hội chủ nghĩa Việt Nam'))
        await fill_select2(shared_page, "#select2-guest_cboRDPROVINCE_ID-container", data.get('tinh', ''))
        await fill_select2(shared_page, "#select2-guest_cboRDADDRESS_ID-container", data.get('xa', ''))
        
        try:
            nationality = data.get('quoc_tich', 'Việt Nam')
            await shared_page.wait_for_selector("#guest_mulNATIONALITY", state="visible", timeout=5000)
            await shared_page.evaluate(f"""
                (nationality) => {{
                    const select = document.getElementById('guest_mulNATIONALITY');
                    if (select) {{
                        for (let option of select.options) {{
                            if (option.text.includes(nationality) || option.text === nationality) {{
                                option.selected = true; break;
                            }}
                        }}
                        select.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                }}
            """, nationality)
        except: pass

        await fill_select2(shared_page, "#select2-guest_cboETHNIC_ID-container", data.get('dan_toc', 'Kinh'))
        await fill_select2(shared_page, "#select2-guest_cboOCCUPATION-container", data.get('nghe_nghiep', 'Tự do'))
        await shared_page.fill("input#guest_txtROOM", data.get('so_phong', ''))
        await shared_page.fill("input#guest_txtPLACE_OF_WORK", data.get('noi_lam_viec', ''))
        await shared_page.fill("textarea#guest_txtREASON", data.get('ly_do', 'làm việc'))
        await shared_page.fill("textarea#guest_txtRDADDRESS", data.get('dia_chi_chi_tiet', ''))
        
        sd = data.get('thoi_gian_luu_tru', '')
        if sd: await shared_page.evaluate(f"document.getElementById('guest_txtSTART_DATE').value = '{sd}'")
        ed = data.get('luu_tru_den', '')
        if ed: await shared_page.evaluate(f"document.getElementById('guest_txtEND_DATE').value = '{ed}'")

        await shared_page.focus("input#guest_txtCITIZENNAME")
        await shared_page.evaluate("document.activeElement.blur()")
        
        await shared_page.click("#btnSaveNLT")
        print(f"[THÀNH CÔNG] Đã lưu: {data.get('ho_ten')}")

        # Thông báo hoàn thành để đổi màu xanh
        await manager.broadcast({"type": "COMPLETED", "index": idx})

        await asyncio.sleep(2) 
        await shared_page.click("a#btnAddPersonLT")
        await shared_page.wait_for_selector("#addpersonLT", state="visible", timeout=10000)
        await asyncio.sleep(1)

    except Exception as e:
        has_error = True
        await manager.broadcast({"type": "ERROR", "index": idx})
        print(f"\n[DỪNG NGAY LẬP TỨC] Lỗi: {e}")
        while not data_queue.empty(): data_queue.get_nowait()

async def process_queue():
    global is_processing, has_error
    is_processing = True
    while not data_queue.empty():
        if has_error: break
        task_item = await data_queue.get()
        await fill_guest_data(task_item)
        data_queue.task_done()
    is_processing = False

@app.post("/send-to-web")
async def receive_data(data: dict, background_tasks: BackgroundTasks):
    global has_error
    has_error = False
    items = data.get("items", [])
    for idx, item in enumerate(items):
        await data_queue.put({"index": idx, "data": item})
    if not is_processing: background_tasks.add_task(process_queue)
    return {"status": "started", "message": f"Bắt đầu xử lý {len(items)} người."}

async def check_url_and_redirect():
    global shared_page
    target_trigger = "https://dichvucong.bocongan.gov.vn/?home=1"
    cong_dan_url = "https://dichvucong.bocongan.gov.vn/dich-vu-cong/cong-dan"
    search_result_url = "https://dichvucong.bocongan.gov.vn/bocongan/bothutuc/listThuTuc?tukhoa=l%C6%B0u%20tr%C3%BA"
    target_destination = "https://dichvucong.bocongan.gov.vn/bo-cong-an/tiep-nhan-online/chon-truong-hop-ho-so?ma-thu-tuc-public=26346"
    while True:
        try:
            if shared_page:
                current_url = shared_page.url
                if cong_dan_url in current_url:
                    await shared_page.goto(search_result_url)
                    await asyncio.sleep(2)
                elif target_trigger in current_url:
                    await shared_page.goto(target_destination)
                    await shared_page.wait_for_load_state("networkidle")
                    await auto_fill_location_and_open_form()
                    break
        except: pass
        await asyncio.sleep(2)

async def main():
    global shared_page
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            shared_page = context.pages[0] if context.pages else await context.new_page()
            print("[HỆ THỐNG] Đã kết nối Chrome.")
            await shared_page.goto("https://dichvucong.bocongan.gov.vn/")
            asyncio.create_task(check_url_and_redirect())
            config = uvicorn.Config(app, host="127.0.0.1", port=8000, loop="asyncio")
            server = uvicorn.Server(config)
            await server.serve()
        except Exception as e: print(f"[LỖI] {e}")

if __name__ == "__main__":
    asyncio.run(main())