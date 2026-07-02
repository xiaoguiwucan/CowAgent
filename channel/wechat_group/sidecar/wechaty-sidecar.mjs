import readline from 'node:readline'
import { WechatyBuilder } from 'wechaty'
import { FileBox } from 'file-box'
import { findContactById, findRoomById, getWechat4uRuntime, isWechat4uBot, sendText as sendTextCore } from './wechaty-sidecar-core.mjs'

const config = JSON.parse(process.argv[2] || '{}')

const state = {
  bot: null,
  self: null,
}

function emit(type, payload = {}) {
  process.stdout.write(JSON.stringify({ type, ...payload }) + '\n')
}

async function listRooms() {
  const rooms = await state.bot.Room.findAll()
  const payload = []
  for (const room of rooms) {
    payload.push({
      id: room.id,
      name: await room.topic(),
    })
  }
  emit('rooms', { rooms: payload })
}

async function contactPayload(contact) {
  return {
    id: contact.id,
    name: contact.name(),
  }
}

async function handleMessage(message) {
  const room = message.room()
  if (!room) return

  const talker = message.talker ? message.talker() : message.from()
  const mentions = await message.mentionList().catch(() => [])
  const self = state.self
  const roomName = await room.topic()
  const talkerInfo = await contactPayload(talker)
  const selfInfo = self ? await contactPayload(self) : { id: '', name: '' }

  emit('message', {
    message_id: message.id,
    timestamp: Math.floor(Date.now() / 1000),
    room_id: room.id,
    room_name: roomName,
    sender_id: talkerInfo.id,
    sender_name: talkerInfo.name,
    self_id: selfInfo.id,
    self_name: selfInfo.name,
    text: message.text(),
    message_type: 'text',
    is_at: self ? mentions.some(contact => contact.id === self.id) : false,
    at_list: mentions.map(contact => contact.id),
    my_msg: self ? talkerInfo.id === self.id : false,
  })
}

async function start() {
  if (state.bot) return
  state.bot = WechatyBuilder.build({
    name: config.memory_path || 'cowagent-wechat-group',
    puppet: config.puppet || 'wechaty-puppet-wechat4u',
  })

  state.bot
    .on('scan', (qrcode, status) => {
      emit('qr', {
        status,
        qrcode,
        url: `https://wechaty.js.org/qrcode/${encodeURIComponent(qrcode)}`,
      })
    })
    .on('login', async user => {
      state.self = user
      emit('status', { status: 'logged_in', self_id: user.id, self_name: user.name() })
      await listRooms()
      emit('status', { status: 'connected', self_id: user.id, self_name: user.name() })
    })
    .on('logout', user => {
      emit('status', { status: 'idle', self_id: user.id, self_name: user.name() })
    })
    .on('message', handleMessage)
    .on('error', error => {
      emit('error', { message: error.message || String(error) })
    })

  emit('status', { status: 'starting' })
  await state.bot.start()
}

async function findRoom(roomId) {
  return findRoomById(state.bot, roomId)
}

async function sendText(command) {
  await sendTextCore(command, {
    emit,
    findRoom,
    findContact: contactId => findContactById(state.bot, contactId),
    getWechat4u: () => getWechat4uRuntime(state.bot),
    isWechat4u: () => isWechat4uBot(state.bot),
  })
}

async function sendFile(command) {
  const room = await findRoom(command.room_id)
  if (!room) throw new Error(`room not found: ${command.room_id}`)
  await room.say(FileBox.fromFile(command.path || command.file_path))
  emit('send_result', { ok: true, command: 'send_file', room_id: command.room_id })
}

async function stop() {
  if (state.bot) {
    await state.bot.stop()
    state.bot = null
  }
  emit('status', { status: 'idle' })
}

async function handleCommand(command) {
  switch (command.type) {
    case 'start':
      await start()
      break
    case 'stop':
      await stop()
      break
    case 'relogin':
      await stop()
      await start()
      break
    case 'list_rooms':
      await listRooms()
      break
    case 'send_text':
      await sendText(command)
      break
    case 'send_file':
    case 'send_image':
    case 'send_audio':
      await sendFile(command)
      break
    default:
      emit('error', { message: `unknown command: ${command.type}` })
  }
}

const rl = readline.createInterface({ input: process.stdin })
rl.on('line', line => {
  Promise.resolve()
    .then(() => handleCommand(JSON.parse(line)))
    .catch(error => emit('error', { message: error.message || String(error) }))
})

start().catch(error => emit('error', { message: error.message || String(error) }))
