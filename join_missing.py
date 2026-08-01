import asyncio
import config
from telethon import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import SearchGlobalRequest
from telethon.tl.types import InputMessagesFilterEmpty
from telethon.errors import FloodWaitError, UserAlreadyParticipantError, ChannelPrivateError

missing = [
    "ASAKA SENTR", "AZAMATPANDA", "Andijon Baliqchi Taxi",
    "Andijon Elonlari", "Andijon Ustalari", "Andijon kv",
    "Andijon ustalar", "Andijon_Ustasi", "Andijon_ustalari N1",
    "Dunyo boylab sayohat", "FAYIZLI BOZOR", "Kabutar Namangan",
    "MADINA_WOP", "MARXAMAT BOZORI", "OLMALIQLIKLAR",
    "Pastayanka", "Quqon ustalar", "SANTEXNIK ANDIJON",
    "Sabina vip kanal", "Stanoklar bozori", "TOSHKENT USTASI",
    "UMRA Rasmiy", "UNVERSAL.UZ", "USTALAR 24/7",
    "Ustala gruppasi", "Vodiy savdo",
    "Андижон Гилам", "Андижон Универсал Усталари",
    "Андижон Элонлари", "Андижон усталари", "Водий бозор",
    "ГАДАЛКА", "ЖАЛАКУДУК", "Жалюзи Андижон",
    "Жалюзи Наманган", "КОРАСУВ УСТАЛАРИ", "Коргонтепа усталари",
    "Кресло Офис", "МАФТУНА", "Маданият бозор",
    "Наманган паталок", "СВАРКА ИШЛАРИ", "ТЕМИР МЕТАЛЛ",
    "Узбегим элонлари", "Фаргона усталари", "Шахрихон усталари",
    "ЯШИРИН ИСТАКЛАР", "ҚОРАСУВ 24",
]

async def main():
    client = TelegramClient('userbot_session', config.API_ID, config.API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print('Session muddati otgan!')
        return

    joined = 0
    failed = []

    for name in missing:
        try:
            result = await client(SearchGlobalRequest(
                q=name, filter=InputMessagesFilterEmpty(),
                min_date=None, max_date=None, offset_rate=0,
                offset_peer='me', offset_id=0, limit=5
            ))
            found = False
            for chat in result.chats:
                if hasattr(chat, 'username') and chat.username:
                    try:
                        await client(JoinChannelRequest(chat))
                        print(f'✅ Qoshildi: {chat.title}')
                        joined += 1
                        found = True
                        await asyncio.sleep(3)
                        break
                    except UserAlreadyParticipantError:
                        print(f'✅ Allaqachon: {chat.title}')
                        found = True
                        break
                    except (ChannelPrivateError, Exception) as e:
                        continue
            if not found:
                failed.append(name)
                print(f'❌ Topilmadi: {name}')
        except FloodWaitError as e:
            print(f'⏳ Flood wait: {e.seconds}s')
            await asyncio.sleep(e.seconds)
        except Exception as e:
            failed.append(name)
            print(f'❌ Xato ({name}): {e}')
        await asyncio.sleep(2)

    print(f'\n✅ Qoshildi: {joined} ta')
    print(f'❌ Topilmadi: {len(failed)} ta')
    if failed:
        print('\nTopilmaganlar (private guruhlar):')
        for g in failed:
            print(f'  - {g}')
    await client.disconnect()

asyncio.run(main())
