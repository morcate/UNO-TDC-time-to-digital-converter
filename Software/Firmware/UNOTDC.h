/*
 * Filename: UNOTDC.h
 * Version: 2.0
 * Date: 2026-06-14
 * Author: Leonardo Lisa, Caterina Morgavi
 * Description: TDC7200 driver declarations and constants.
 *
 */

#ifndef UNOTDC_H_
#define UNOTDC_H_

#include <Arduino.h>
#include "synchronousSPI.h"

/* Data format option */
//#define EASYDATA
//#define RAWDATA

/* TDC7200 enable time */
#define TDC_ENABLE_TIME 2 // ms

/* TXU0104 enable time */
// #define TXU_ENABLE_TIME // 33 ns

/* TDC7200 register mapping */
#define CONFIG1 0x00
#define CONFIG2 0x01
#define INT_STATUS 0x02
#define INT_MASK 0x03
#define COARSE_CNTR_OVF_H 0x04
#define COARSE_CNTR_OVF_L 0x05
#define TIME1 0x10
#define CLOCK_COUNT1 0x11
#define TIME2 0x12
#define CLOCK_COUNT2 0x13
#define TIME3 0x14
#define CLOCK_COUNT3 0x15
#define TIME4 0x16
#define CLOCK_COUNT4 0x17
#define TIME5 0x18
#define CLOCK_COUNT5 0x19
#define TIME6 0x1a
#define CALIBRATION1 0x1b
#define CALIBRATION2 0x1c

/* TDC7200 command mask */
#define RW 0x40
#define AUTO_INC_MODE 0x80

/* ArduinoUNO pin mapping (SPI pins in synchronousSPI.h) */
#define CS 0x04     // PB2 10 -> TDC7200 CSB
#define ENABLE 0x01 // PB0 8  -> TDC7200 ENABLE
#define TRIG 0x04   // PD2 2 (INT0) -> TDC7200 TRIG
#define INTB 0x08   // PD3 3 (INT1) -> TDC7200 INTB

#define OE 0x20   // PB5 13 -> TXU01014 OE

#define LED_R 0x01   // PC0 A0 -> KING LED_R
#define LED_G 0x02   // PC1 A1 -> KING LED_G
#define LED_B 0x04   // PC2 A2 -> KING LED_B


/* Serial TX buffer */
#define PENDING_DATA 1
#define DATA_SENT 0
#define BUF_SIZE 4
#define IS_LOST 1

/* Data struct */
class UNO_TDC
{
public:
  uint8_t time1_r[3]; // Why use uint24_t when you only need a 24bit container?
  uint8_t time2_r[3];
  uint8_t clock_count1_r[3];
  uint8_t cal1_r[3];
  uint8_t cal2_r[3];
  uint8_t status = DATA_SENT;
};

/* External global variables linking */
extern volatile UNO_TDC buf[BUF_SIZE];
extern volatile uint8_t buf_index;
extern volatile uint8_t data_lost_flag;
extern volatile uint8_t mode;

/* Functions declarations */
void initializeTDC(void);
void startMeasurement1(void);
void firstStartMeasurement1(void);
void startMeasurement2(void);
void firstStartMeasurement2(void);
void getMeasurement1(void);
void getMeasurement2(void);
void printData1(uint8_t _index);
void printData2(uint8_t _index);

#endif // UNOTDC_H_