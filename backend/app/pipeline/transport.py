from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

transport_params = {
    "websocket": lambda: FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        add_wav_header=False,
        serializer=ProtobufFrameSerializer(),
    ),
}
