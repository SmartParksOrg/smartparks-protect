/*
 * AWT collar uplink decoder
 * TS013-1.0.0 Payload Codec API compatible
 * Tested model: ChirpStack v4-style codec engine
 *
 * Entry point (as required by TS013 & ChirpStack v4):
 *
 *   function decodeUplink(input) {
 *     // input.bytes : number[]
 *     // input.fPort : number
 *     // input.recvTime : Date   (TS013) – may be absent in ChirpStack
 *     // input.variables : Object (ChirpStack) – non-standard TS013, optional
 *     // return { data: {...}, errors?: [...], warnings?: [...] }
 *   }
 */

function toUint16(highByte, lowByte) {
  return (highByte << 8) | lowByte;
}

function toInt16(highByte, lowByte) {
  var value = (highByte << 8) | lowByte;
  if (value > 0x7FFF) {
    value -= 0x10000;
  }
  return value;
}

function toUint32(byte0, byte1, byte2, byte3) {
  return (byte0 << 24) | (byte1 << 16) | (byte2 << 8) | byte3;
}

function extractBits(value, startBit, endBit) {
  var mask = (1 << (endBit - startBit + 1)) - 1;
  return (value >> startBit) & mask;
}

function dec2bin(dec) {
  return (dec >>> 0).toString(2);
}

function padDigits(number, digits) {
  var str = number.toString();
  while (str.length < digits) {
    str = '0' + str;
  }
  return str;
}

// Calculate XOR sum for CRC
function calculateXORCRC(bytes, start, end) {
  var crc = 0;
  for (var i = start; i <= end; i++) {
    crc ^= bytes[i];
  }
  return crc;
}

/*
 * Internal decoder with your original logic, turned into a helper.
 * This is essentially your old Decode(fPort, bytes, variables) function,
 * just renamed so decodeUplink(...) can call it.
 */
function decodeAWTUplink(fPort, bytes, variables) {
  var decoded = {};

  decoded.header = bytes[0];
  decoded.messageCounter = bytes[1];

  // Command byte (0x91 for Encrypted, 0xD1 for Not Encrypted)
  decoded.command = bytes[2] === 0x91 ? "Encrypted" : "Not Encrypted";

  decoded.payloadLength = bytes[3];

  // Calculate and verify Header CRC (XOR sum of header bytes 0 to 3)
  var expectedHeaderCRC = calculateXORCRC(bytes, 0, 3);
  decoded.headerCRC = expectedHeaderCRC === bytes[4];

  // Sub Command byte
  var subCommandMapping = {
    0x00: "AWT Minimal payload type",
    0x01: "AWT Standard payload type",
    0x03: "AWT Standard payload type + altitude",
    0x04: "AWT Standard payload type + light",
    0x05: "AWT Standard payload type + altitude + light"
  };
  decoded.subCommand = subCommandMapping[bytes[5]] || "Unknown Sub Command";

  // Tag ID and Master Tag ID
  decoded.masterTagID = toUint16(bytes[7], bytes[6]);
  decoded.tagID = toUint16(bytes[9], bytes[8]);

  // Alarms
  decoded.alarms = {
    otaTrackMode: (bytes[10] & 0x01) !== 0,
    lowBattery: (bytes[10] & 0x02) !== 0,
    tamperFoil: (bytes[10] & 0x08) !== 0,
    serviceCoverage: (bytes[10] & 0x20) !== 0,
    memoryFull: (bytes[10] & 0x40) !== 0,
    selfTestResult: (bytes[10] & 0x80) !== 0
  };

  decoded.ackRetries = {
    humidityAlarm: (bytes[11] & 0x01) !== 0,
    pollingOn: (bytes[11] & 0x02) !== 0,
    bleCommandAck: (bytes[11] & 0x04) !== 0,
    uhfCommandAck: (bytes[11] & 0x08) !== 0,
    otaCommandAck: (bytes[11] & 0x10) !== 0,
    uploadRetry: bytes[11] >> 5
  };

  // Software version
  decoded.softwareVersion = bytes[12];

  // Reporting interval
  var reportingIntervals = {
    0: "Off",
    1: "GPS log every 10 minutes",
    2: "GPS log every 1 hour",
    3: "GPS log every 6 hours",
    4: "GPS log every 12 hours",
    5: "GPS log every 24 hours",
    7: "GPS log every 3 hours",
    15: "GPS log every 30 minutes",
    16: "GPS log every 2 hours",
    17: "GPS log every 4 hours",
    18: "GPS log every 5 hours",
    19: "GPS log every 8 hours",
    20: "Custom Interval"
  };
  decoded.reportingInterval = reportingIntervals[bytes[13]] || "Unknown Interval";

  // Battery voltage
  decoded.batteryVoltage = toUint16(bytes[14], bytes[15]) / 100;

  // Epoch time
  var epochTime = toUint32(bytes[16], bytes[17], bytes[18], bytes[19]);
  decoded.timestamp = epochTime; // Raw Unix timestamp
  decoded.epochTime = new Date(epochTime * 1000).toISOString(); // ISO format

  // GPS Latitude
  try {
    var latitudeString = dec2bin(
      (bytes[20] << 24) |
      (bytes[21] << 16) |
      (bytes[22] << 8) |
      bytes[23]
    );
    var latitudeInt = padDigits(
      parseInt(latitudeString.substring(latitudeString.length - 27), 2),
      8
    );
    var latDeg = parseInt(latitudeInt.substring(0, 2), 10);
    var latDecimal = parseFloat(
      ((parseInt(latitudeInt.substring(2, 8), 10) / 10000) / 60).toPrecision(5)
    );
    var southNorth = 1;
    if (latitudeString.substring(0, 1) === "1") {
      southNorth = -1;
    }
    decoded.latitude = (latDeg + latDecimal) * southNorth;
  } catch (exception_var) {
    decoded.latitude = 0;
  }

  // HDOP (Bits 27-30 of GPS Latitude)
  // NOTE: This follows your original implementation and might need review
  // against AWT GPS encoding docs if HDOP values look off.
  decoded.hdop = extractBits(bytes[20], 27, 30);

  // GPS Longitude
  try {
    var longitudeString = dec2bin(
      (bytes[24] << 24) |
      (bytes[25] << 16) |
      (bytes[26] << 8) |
      bytes[27]
    );
    var longitudeInt = padDigits(
      parseInt(longitudeString.substring(longitudeString.length - 28), 2),
      9
    );
    var lonDeg = parseInt(longitudeInt.substring(0, 3), 10);
    var lonDecimal = parseFloat(
      ((parseInt(longitudeInt.substring(3, 9), 10) / 10000) / 60).toPrecision(5)
    );
    var eastWest = 1;
    if (longitudeString.substring(0, 1) === "0") {
      eastWest = -1;
    }
    decoded.longitude = (lonDeg + lonDecimal) * eastWest;
  } catch (exception_var2) {
    decoded.longitude = 0;
  }

  // Extract flags from GPS Longitude
  decoded.alarmFlag = (bytes[24] & 0x40) !== 0;
  decoded.movementFlag = (bytes[24] & 0x20) !== 0;
  decoded.globalAck = (bytes[24] & 0x10) !== 0;

  // Ground speed
  decoded.groundSpeed = bytes[28];

  // Message Key
  decoded.messageKey = bytes[29];

  // Accelerometer data
  decoded.accelerometer = {
    x: toInt16(bytes[30], bytes[31]),
    y: toInt16(bytes[32], bytes[33]),
    z: toInt16(bytes[34], bytes[35])
  };

  // Temperature
  decoded.temperature = bytes[36];

  // Altitude (if present)
  if (bytes.length > 38) {
    decoded.altitude = toUint16(bytes[37], bytes[38]);
  }

  // Light level (if present)
  if (bytes.length > 40) {
    decoded.lightLevel = toUint16(bytes[39], bytes[40]);
  }

  // Calculate and verify Payload CRC (XOR sum of payload bytes)
  var payloadEndIndex = bytes.length - 2;
  var expectedPayloadCRC = calculateXORCRC(bytes, 5, payloadEndIndex);
  decoded.payloadCRC = expectedPayloadCRC === bytes[bytes.length - 1];

  return decoded;
}

/*
 * TS013 / ChirpStack v4 entry point
 */
function decodeUplink(input) {
  // Basic validation
  if (!input || !input.bytes || input.bytes.length === 0) {
    return {
      errors: ["Empty or invalid payload"],
      // data is optional when errors are present, per TS013
    };
  }

  var bytes = input.bytes;
  var fPort = input.fPort;
  // In ChirpStack, "variables" is provided instead of "recvTime" from TS013.
  // We keep it optional and do not rely on it.
  var variables = input.variables || {};

  try {
    var decoded = decodeAWTUplink(fPort, bytes, variables);

    return {
      data: decoded
      // Optionally you could add warnings: [] here later
    };
  } catch (e) {
    // In case something goes wrong, report a TS013-style error list.
    return {
      errors: ["Decoder exception: " + String(e)]
    };
  }
}
