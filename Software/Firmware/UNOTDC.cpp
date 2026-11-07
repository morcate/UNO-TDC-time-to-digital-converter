/*
 * Filename: UNOTDC.cpp
 * Version: 2.0
 * Date: 2026-06-14
 * Author: Leonardo Lisa, Caterina Morgavi
 * Description: TDC7200 driver function implementations.
 *
 */

#include "UNOTDC.h"
#include <avr/interrupt.h>

void initializeTDC(void)
{
  /* Pinmode settings */
  cli(); // Disable interrupts

  // D
  DDRD &= (~TRIG);
  DDRD &= (~INTB);
  PORTD &= (~TRIG);
  PORTD &= (~INTB);
  //PORTD |= TRIG; // Enable 50k internal pullup resistor.

  // B
  DDRB |= CS | SCLK | DOUT | ENABLE | OE;
  DDRB &= ~DIN;
  PORTB |= ENABLE | CS;
  PORTB &= ~(SCLK | DOUT | DIN | OE);

  // C
  DDRC |= LED_B | LED_G | LED_R;
  PORTC |= LED_R;
  PORTC &= ~(LED_B | LED_G);

  sei(); // Enable interrupts

  // Enabling TXU0104
  PORTB |= OE; 

  /* WARNING: TXU_ENABLE_TIME is only 33 nanoseconds!
  if (TDC_ENABLE_TIME > TXU_ENABLE_TIME)
  {
    delay(TDC_ENABLE_TIME);
  }
  else
  {
    delay(TXU_ENABLE_TIME)
  };
  */
  delay(TDC_ENABLE_TIME);

  /* TDC7200 register setup */
  cli(); // Disable interrupts

  // CONFIG1 configuration
  // 0 Start New Measurement
  // 00 Measurement Mode 1
  // 0 Measurement is started on Rising edge of START signal
  // 0 Measurement is stopped on Rising edge of STOP signal
  // 0 TRIGG is output as a Rising edge signal
  // 0 Parity bit for Measurement Result Registers disabled (Parity Bit always 0)
  // 0 Calibration is not performed after interrupted measurement (for example, due to counter overflow or missing STOP signal)
  // 0b00000000 is the reset value.

  // CONFIG2 configuration
  // 01 calibration, measuring 10 CLOCK periods
  // 000 no Multi-Cycle Averaging Mode
  // 000 Single stop
  // 0b01000000
  PORTB &= ~CS; // Start transaction
  shiftOutMSB((CONFIG2 | RW)); // Send write command
  shiftOutMSB(0b01000000);
  PORTB |= CS; // End transaction

  __asm__("nop\n\t"); // Minimum pause time (CS high) is 40ns

  // INT_MASK configuration
  // 00000 reserved
  // 0 CLOCK Counter Overflow Interrupt disabled
  // 0 Coarse Counter Overflow Interrupt disabled
  // 1 New Measurement Interrupt
  PORTB &= ~CS; // Start transaction
  shiftOutMSB((INT_MASK | RW)); // Send write command
  shiftOutMSB(0b00000111);
  PORTB |= CS; // End transaction

  /* Setting ISR */
  // 0bxxxxxx10 attach interrupt on TRIG to trigger on falling edge.
  EICRA = 0b00000010;
  // 0bxxxxxxx1 enable external interrupt on TRIG
  EIMSK = 0b00000001;

  sei(); // Enable interrupts
}

void firstStartMeasurement1(void)
{
  cli(); // Disable interrupts

  PORTB &= ~CS;                // Start transaction
  shiftOutMSB((CONFIG1 | RW)); // Send write command
  shiftOutMSB(0b00000001);
  // CONFIG1 configuration
  // 0 No FORCE_CAL
  // 0 No parity
  // 0
  // 0 Measurement is stopped on Rising edge of STOP signal
  // 0 Measurement is started on Rising edge of START signal
  // 00 Measurement Mode 1
  // 1 Start New Measurement
  // 0b00000001
  PORTB |= CS; // End transaction

  sei(); // Enable interrupts
}

void startMeasurement1(void)
{
  PORTB &= ~CS;                // Start transaction
  shiftOutMSB((CONFIG1 | RW)); // Send write command
  shiftOutMSB(0b00000001);
  PORTB |= CS; // End transaction
}

void firstStartMeasurement2(void)
{
  cli(); // Disable interrupts

  PORTB &= ~CS;                // Start transaction
  shiftOutMSB((CONFIG1 | RW)); // Send write command
  shiftOutMSB(0b00000011);
  // CONFIG1 configuration
  // 0 No FORCE_CAL
  // 0 No parity
  // 0
  // 0 Measurement is stopped on Rising edge of STOP signal
  // 0 Measurement is started on Rising edge of START signal
  // 01 Measurement Mode 2
  // 1 Start New Measurement
  // 0b00000011
  PORTB |= CS; // End transaction

  sei(); // Enable interrupts
}

void startMeasurement2(void)
{
  PORTB &= ~CS;                // Start transaction
  shiftOutMSB((CONFIG1 | RW)); // Send write command
  shiftOutMSB(0b00000011);
  PORTB |= CS; // End transaction
}

void getMeasurement1(void)
{
  uint8_t _index = BUF_SIZE;

  /* Finding a spot for Data */
  for (uint8_t i = 0; i < BUF_SIZE; i++)
  {
    if (buf[i].status == DATA_SENT) // Add "(i != acquire_flag) &&" if you edit loop code
    {
      _index = i;
      break;
    }
  }
  
  // Fatal error: measure abort
  // No available space in serial buffer
  if (_index == BUF_SIZE)
  {
    data_lost_flag++;
    return;
  }

  /* Use INT_STATUS register to check if the measurement is complete. Otherwise discard measurement
  PORTB &= ~CS;       
  // Start transaction
  shiftOutMSB(INT_STATUS | AUTO_INC_MODE);
  // One byte
  meas_status = getByte() & 0b00010001;
  PORTB |= CS; // End transaction
  __asm__("nop\n\t"); // Minimum pause time (CS high) is 40ns

  if (meas_status != 0b00010001) {
    data_lost_flag++;
    return;
  }
  */

  /* Harvesting data from TDC7200 */

  /*TIME 1*/
  PORTB &= ~CS;                       // Start transaction
  // Send command
  // 0x80 for auto-increment, 0x40 set R or W mode (1 is W)
  shiftOutMSB(TIME1 | AUTO_INC_MODE); // Request TIME1 data
  // Most significant BYTE first
  for (uint8_t i = 0; i < 3; i++)
  {
    buf[_index].time1_r[2 - i] = getByte();
  }
  PORTB |= CS;                       // End transaction
  __asm__("nop\n\t"); // Minimum pause time (CS high) is 40ns

  /*CALIBRATION 1*/
  PORTB &= ~CS;                              // Start transaction
  shiftOutMSB(CALIBRATION1 | AUTO_INC_MODE); // Request CALIBRATION1 data
  // Most significant BYTE first
  for (uint8_t i = 0; i < 3; i++)
  {
    buf[_index].cal1_r[2 - i] = getByte();
  }
  PORTB |= CS;                               // End transaction
  __asm__("nop\n\t"); // Minimum pause time (CS high) is 40ns

  /*CALIBRATION 2*/
  PORTB &= ~CS;                              // Start transaction
  shiftOutMSB(CALIBRATION2 | AUTO_INC_MODE); // Request CALIBRATION2 data
  // Most significant BYTE first
  for (uint8_t i = 0; i < 3; i++)
  {
    buf[_index].cal2_r[2 - i] = getByte();
  }
  PORTB |= CS;                               // End transaction
  __asm__("nop\n\t"); // Minimum pause time (CS high) is 40ns


  buf[_index].status = PENDING_DATA; // Data ready to be sent
}

void getMeasurement2(void)
{
  uint8_t _index = BUF_SIZE;

  /* Finding a spot for Data */
  for (uint8_t i = 0; i < BUF_SIZE; i++)
  {
    if (buf[i].status == DATA_SENT) // Add "(i != acquire_flag) &&" if you edit loop code
    {
      _index = i;
      break;
    }
  }

  // Fatal error: measure abort
  // No available space in serial buffer
  if (_index == BUF_SIZE)
  {
    data_lost_flag++;
    return;
  }

  /* Use INT_STATUS register to check if the measurement is complete. Otherwise discard measurement
  PORTB &= ~CS;       
  // Start transaction
  shiftOutMSB(INT_STATUS | AUTO_INC_MODE);
  // One byte
  meas_status = getByte() & 0b00010001;
  PORTB |= CS; // End transaction
  __asm__("nop\n\t"); // Minimum pause time (CS high) is 40ns

  if (meas_status != 0b00010001) {
    data_lost_flag++;
    return;
  }
  */

  /* Harvesting data from TDC7200 */

  PORTB &= ~CS;                       // Start transaction
  // Send command
  // 0x80 for auto-increment, 0x40 set R or W mode (1 is W)
  shiftOutMSB(TIME1 | AUTO_INC_MODE); // Request TIME1 data
  // Most significant BYTE first
  /*TIME 1*/
  for (uint8_t i = 0; i < 3; i++)
  {
    buf[_index].time1_r[2 - i] = getByte();
  }

  /*CLOCK_COUNT 1*/
  for (uint8_t i = 0; i < 3; i++)
  {
    buf[_index].clock_count1_r[2 - i] = getByte();
  }

  /*TIME 2*/
  for (uint8_t i = 0; i < 3; i++)
  {
    buf[_index].time2_r[2 - i] = getByte();
  }
  PORTB |= CS;
  __asm__("nop\n\t");


  /*CALIBRATION 1*/
  PORTB &= ~CS;                              // Start transaction
  shiftOutMSB(CALIBRATION1 | AUTO_INC_MODE); // Request CALIBRATION1 data
  // Most significant BYTE first
  for (uint8_t i = 0; i < 3; i++)
  {
    buf[_index].cal1_r[2 - i] = getByte();
  }
  PORTB |= CS;                               // End transaction
  __asm__("nop\n\t"); // Minimum pause time (CS high) is 40ns

  /*CALIBRATION 2*/
  PORTB &= ~CS;                              // Start transaction
  shiftOutMSB(CALIBRATION2 | AUTO_INC_MODE); // Request CALIBRATION2 data
  // Most significant BYTE first
  for (uint8_t i = 0; i < 3; i++)
  {
    buf[_index].cal2_r[2 - i] = getByte();
  }
  PORTB |= CS;                               // End transaction
  __asm__("nop\n\t"); // Minimum pause time (CS high) is 40ns


  buf[_index].status = PENDING_DATA; // Data ready to be sent
}

void printData1(uint8_t _index)
{
#ifdef EASYDATA
  uint32_t cal1 = ((uint32_t)buf[_index].cal1_r[2] << 16) | ((uint32_t)buf[_index].cal1_r[1] << 8) | buf[_index].cal1_r[0];
  uint32_t cal2 = ((uint32_t)buf[_index].cal2_r[2] << 16) | ((uint32_t)buf[_index].cal2_r[1] << 8) | buf[_index].cal2_r[0];

  double Difference = static_cast<double>(cal2 - cal1);

  double rawTime = static_cast<uint32_t>(buf[_index].time1_r[2])*(uint32_t)65536 +
                   static_cast<uint32_t>(buf[_index].time1_r[1])*(uint32_t)256 +
                   static_cast<uint32_t>(buf[_index].time1_r[0]);
  //Serial.print(F("ToF is: "));
  Serial.println((rawTime * 562.5) / Difference);
#elif defined(RAWDATA)
  Serial.print(F("time1_r = "));
  Serial.print(buf[_index].time1_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].time1_r[1]);
  Serial.write(' ');
  Serial.println(buf[_index].time1_r[0]);

  Serial.print(F("cal1_r = "));
  Serial.print(buf[_index].cal1_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].cal1_r[1]);
  Serial.write(' ');
  Serial.println(buf[_index].cal1_r[0]);

  Serial.print(F("cal2_r = "));
  Serial.print(buf[_index].cal2_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].cal2_r[1]);
  Serial.write(' ');
  Serial.println(buf[_index].cal2_r[0]);
#else 
  Serial.print(buf[_index].time1_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].time1_r[1]);
  Serial.write(' ');
  Serial.print(buf[_index].time1_r[0]);
  Serial.write(' ');
  Serial.print(buf[_index].cal1_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].cal1_r[1]);
  Serial.write(' ');
  Serial.print(buf[_index].cal1_r[0]);
  Serial.write(' ');
  Serial.print(buf[_index].cal2_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].cal2_r[1]);
  Serial.write(' ');
  Serial.println(buf[_index].cal2_r[0]);
  //Serial.write(' ');
  //Serial.print(buf[_index].interrupt_status1_r, HEX);
  //Serial.write(' ');
  //Serial.print(buf[_index].interrupt_status2_r, HEX);
  //Serial.write('       ');
  //Serial.println(buf[_index].overflow_flag_r);
#endif
}

void printData2(uint8_t _index)
{
#ifdef EASYDATA
  uint32_t cal1 = ((uint32_t)buf[_index].cal1_r[2] << 16) | ((uint32_t)buf[_index].cal1_r[1] << 8) | buf[_index].cal1_r[0];
  uint32_t cal2 = ((uint32_t)buf[_index].cal2_r[2] << 16) | ((uint32_t)buf[_index].cal2_r[1] << 8) | buf[_index].cal2_r[0];

  double Difference = static_cast<double>(cal2 - cal1);

  double rawTime1 = static_cast<uint32_t>(buf[_index].time1_r[2])*(uint32_t)65536 +
                   static_cast<uint32_t>(buf[_index].time1_r[1])*(uint32_t)256 +
                   static_cast<uint32_t>(buf[_index].time1_r[0]);

   double rawTime2 = static_cast<uint32_t>(buf[_index].time2_r[2])*(uint32_t)65536 +
                   static_cast<uint32_t>(buf[_index].time2_r[1])*(uint32_t)256 +
                   static_cast<uint32_t>(buf[_index].time2_r[0]);

   double raw_cc_1 = static_cast<uint32_t>(buf[_index].clock_count1_r[2])*(uint32_t)65536 +
                   static_cast<uint32_t>(buf[_index].clock_count1_r[1])*(uint32_t)256 +
                   static_cast<uint32_t>(buf[_index].clock_count1_r[0]);
                 
  //Serial.print(F("ToF is: "));
  Serial.println((62.5 * raw_cc_1) + (562.5)*(rawTime1-rawTime2) / Difference);

#elif defined(RAWDATA)
  Serial.print(F("time1_r = "));
  Serial.print(buf[_index].time1_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].time1_r[1]);
  Serial.write(' ');
  Serial.println(buf[_index].time1_r[0]);

  Serial.print(F("clock_count1_r = "));
  Serial.print(buf[_index].clock_count1_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].clock_count1_r[1]);
  Serial.write(' ');
  Serial.println(buf[_index].clock_count1_r[0]);

  Serial.print(F("time2_r = "));
  Serial.print(buf[_index].time2_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].time2_r[1]);
  Serial.write(' ');
  Serial.println(buf[_index].time2_r[0]);

  Serial.print(F("cal1_r = "));
  Serial.print(buf[_index].cal1_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].cal1_r[1]);
  Serial.write(' ');
  Serial.println(buf[_index].cal1_r[0]);

  Serial.print(F("cal2_r = "));
  Serial.print(buf[_index].cal2_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].cal2_r[1]);
  Serial.write(' ');
  Serial.println(buf[_index].cal2_r[0]);
#else 
  Serial.print(buf[_index].time1_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].time1_r[1]);
  Serial.write(' ');
  Serial.print(buf[_index].time1_r[0]);
  Serial.write(' ');
  
  Serial.print(buf[_index].clock_count1_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].clock_count1_r[1]);
  Serial.write(' ');
  Serial.print(buf[_index].clock_count1_r[0]);
  Serial.write(' ');
  
  Serial.print(buf[_index].time2_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].time2_r[1]);
  Serial.write(' ');
  Serial.print(buf[_index].time2_r[0]);
  Serial.write(' ');
  
  Serial.print(buf[_index].cal1_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].cal1_r[1]);
  Serial.write(' ');
  Serial.print(buf[_index].cal1_r[0]);
  Serial.write(' ');
  
  Serial.print(buf[_index].cal2_r[2]);
  Serial.write(' ');
  Serial.print(buf[_index].cal2_r[1]);
  Serial.write(' ');
  Serial.println(buf[_index].cal2_r[0]);
#endif
}