/*
 * Filename: UNO-TDC.ino
 * Version: 2.0
 * Date: 2026-06-14
 * Author: Leonardo Lisa, Caterina Morgavi
 * Description: Main entry point for UNO-TDC measurement system.
 *
 */

#include <avr/interrupt.h>
#include "UNOTDC.h" // Inclusions cascade: UNOTDC.h -> synchronousSPI.h

/* Serial circular buffer instantiation */
volatile UNO_TDC buf[BUF_SIZE];
volatile uint8_t buf_index = 0;      // Buffer index
volatile uint8_t data_lost_flag = 0; // Buffer is full

/*Measurement mode flag*/
volatile uint8_t mode = 1;

void setup()
{
  Serial.begin(38400);
  Serial.flush();
  delay(100);
  Serial.println(F("Initializing TDC..."));
  initializeTDC();

  Serial.println(F("$$\\   $$\\$$\\   $$\\ $$$$$$\\   $$\\          $$\\"));
  Serial.println(F("$$ |  $$ $$$\\  $$ $$  __$$\\  $$ |         $$ |"));
  Serial.println(F("$$ |  $$ $$$$\\ $$ $$ /  $$ $$$$$$\\   $$$$$$$ |$$$$$$$\\"));
  Serial.println(F("$$ |  $$ $$ $$\\$$ $$ |  $$ \\_$$  _| $$  __$$ $$  _____|"));
  Serial.println(F("$$ |  $$ $$ \\$$$$ $$ |  $$ | $$ |   $$ /  $$ $$ /"));
  Serial.println(F("$$ |  $$ $$ |\\$$$ $$ |  $$ | $$ |$$\\$$ |  $$ $$ |"));
  Serial.println(F("\\$$$$$$  $$ | \\$$ |$$$$$$  | \\$$$$  \\$$$$$$$ \\$$$$$$$\\"));
  Serial.println(F(" \\______/\\__|  \\__|\\______/   \\____/ \\_______|\\_______|"));
  Serial.println();
  Serial.println(F("Università degli Studi di Milano, Milano 2026"));
  Serial.println();
  Serial.println(F("UNO-TDC Copyright (C) 2026 Leonardo Lisa and Caterina Morgavi"));
  Serial.println(F("This program comes with ABSOLUTELY NO WARRANTY."));
  Serial.println(F("This is free software, and you are welcome to redistribute it under the GNU General Public License v3 conditions."));
  Serial.println();
  Serial.println();
  Serial.println();
  Serial.println(F("SELECT MEASUREMENT MODE"));
  Serial.println(F("Press 1 for Measurement Mode 1, or press 2 for Measurement Mode 2"));

  while (true)
  {
    if (Serial.available() > 0)
    {
      // Read the incoming byte
      char rxByte = Serial.read();
      
      // Break the loop only if '1' or '2' is received
      // Write the input as the mode
      if (rxByte == '1')
      {
        break;
      }

      if (rxByte == '2')
      {
        mode = 2;
        break;
      }
    }
    __asm__("nop\n\t");
  }

  Serial.print(F("You have selected measurement mode "));
  Serial.println(mode);
  Serial.println();

  // Discard leftover RX (CR/LF or terminal echo after '1'/'2') so the start
  // wait cannot unblock on the same keystroke line.
  delay(20);
  while (Serial.available() > 0)
  {
    (void)Serial.read();
  }

  Serial.println(F("Press any key to start acquisition"));
  while (Serial.available() == 0)
  {
    __asm__("nop\n\t");
  }
  // Consume the start key (and any trailing CR/LF) before arming.
  delay(20);
  while (Serial.available() > 0)
  {
    (void)Serial.read();
  }

  if (mode == 1){
    firstStartMeasurement1();
  }
  else{
    firstStartMeasurement2();
  }
  
}

void loop()
{
  /* Send measurements */
  if (buf[buf_index].status == PENDING_DATA)
  {
    if (mode == 1){
      printData1(buf_index);
    }
    else{
      printData2(buf_index);
    }  
    
    buf[buf_index].status = DATA_SENT;
  }

  if (!!(data_lost_flag) == IS_LOST)
  {
    Serial.print(F("ERROR! "));
    Serial.print(data_lost_flag);
    Serial.println(F(" measurements lost :("));
    cli(); // Disable interrupts
    data_lost_flag = 0;
    sei(); // Enable interrupts
  }

  if (buf_index >= (BUF_SIZE - 1))
  {
    buf_index = 0;
  }
  else
  {
    buf_index++;
  }
}

/* ISR */
// Newest TDC measurement ready for reading
ISR(INT0_vect)
{
  if (mode == 1)
  {
    getMeasurement1();
    startMeasurement1();                  // End transaction
  } else {
    getMeasurement2();
    startMeasurement2();                  // End transaction
  }

}