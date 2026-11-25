settings.server.telnet.set(true)
settings.server.telnet.bind_addr.set("0.0.0.0")
settings.server.telnet.port.set(1234)

# Read ordered M3U playlist managed by our Python backend
my_playlist = playlist(id="main_playlist", mode="normal", reload_mode="watch", "/music/playlist.m3u")

radio = normalize(my_playlist)
radio = crossfade(duration=2.0, radio)
radio = mksafe(radio)

output.icecast(
  id="broadcast",
  %mp3(bitrate=128),
  host="icecast",
  port=8000,
  password="__SOURCE_PASS__",
  mount="/stream.mp3",
  connection_timeout=1.0,
  name="Ghammas Baladi Official Radio",
  description="Centralized Branch Broadcast - CDR Group",
  radio
)
