# Database Knowledgebase System Analytics Report

This report captures the automated execution of all defined test questions against the Database Knowledgebase pipeline.

---

## Level 1 - Basic Select and Filters

### Q: How much time did employee Ebenezar S spend at work on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 6.18s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **At Work Second**: 35880
- **Attendance Date**: 2026-09-01
- **Attendance Clock In**: 09:45:17
- **Attendance Clock Out**: 19:58:23
- **Attendance Worked Hour**: 09:58
- **Badge Id**: 9
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
```

### Q: What was Ebenezar S's clock-in time on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 1.68s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Date**: 2026-09-01
- **Attendance Clock In**: 09:45:17
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Gender**: male
- **Attendance Overtime**: 01:48
```

### Q: What was Ebenezar S's clock-out time on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 1.52s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Clock Out**: 19:58:23
- **Attendance Date**: 2026-09-01
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Gender**: male
- **Attendance Overtime**: 01:48
```

### Q: How many hours did Ebenezar S work on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 1.59s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total count is 9.
```

### Q: How many seconds was Ebenezar S recorded as being at work on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 19.72s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total count is 1.
```

### Q: Did Ebenezar S have an attendance record on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 0.92s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Clock Out**: 19:58:23
- **Attendance Date**: 2026-09-01
- **Attendance Clock In**: 09:45:17
- **Badge Id**: 9
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Gender**: male
```

### Q: What was the attendance status of Ebenezar S on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 1.04s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Clock Out**: 19:58:23
- **Attendance Date**: 2026-09-01
- **Attendance Clock In**: 09:45:17
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **State**: Tamil Nadu
- **Gender**: male
```

### Q: Show Ebenezar S's complete attendance information for 2026-09-01.
- **Status**: ✅ PASSED
- **Time**: 1.06s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Clock Out**: 19:58:23
- **Attendance Date**: 2026-09-01
- **Attendance Clock In**: 09:45:17
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Gender**: male
- **Qualification**: Bsc IT
- **Attendance Overtime**: 01:48
```

### Q: What time did Ebenezar S enter and leave the workplace on 2026-09-01?
- **Status**: ❌ FAILED
- **Time**: 2.61s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: Was Ebenezar S present for the full working day on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 1.34s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **At Work Second**: 35880
- **Attendance Date**: 2026-09-01
- **Attendance Clock In**: 09:45:17
- **Attendance Clock Out**: 19:58:23
- **Attendance Worked Hour**: 09:58
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Gender**: male
```

## Level 2 - Aggregations and Grouping

### Q: Find the attendance record for employee last name S and first name Ebenezar on a specific date.
- **Status**: ❌ FAILED
- **Time**: 6.75s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: What is the employee ID of Ebenezar S?
- **Status**: ✅ PASSED
- **Time**: 12.56s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Badge Id**: 9
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Gender**: male
```

### Q: What badge ID belongs to Ebenezar S?
- **Status**: ✅ PASSED
- **Time**: 2.58s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Badge Id**: 9
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Gender**: male
```

### Q: Find the employee whose first name is Ebenezar and last name is S, then retrieve their attendance for a given date.
- **Status**: ✅ PASSED
- **Time**: 10.78s
- **Database Rows Processed**: 100
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
| Attendance Clock Out | Attendance Date | Attendance Clock In | Employee Last Name | Employee First Name | Gender | State | Attendance Overtime |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 19:38:00 | 2025-06-30 | 19:38:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 20:39:00 | 2025-07-01 | 13:51:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 13:29:00 | 2025-07-02 | 10:27:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:13:00 | 2025-07-03 | 10:16:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:40:00 | 2025-07-04 | 10:19:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:17:00 | 2025-07-05 | 10:24:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| - | 2025-07-07 | 09:52:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:08:00 | 2025-07-23 | 10:35:00 | S | Ebenezar | male | Tamil Nadu | 00:23 |
| 19:14:00 | 2025-07-24 | 10:16:00 | S | Ebenezar | male | Tamil Nadu | 00:05 |
| - | 2025-07-09 | 10:03:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| - | 2025-07-10 | 10:28:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| - | 2025-07-21 | 10:11:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| - | 2025-07-11 | 10:56:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| - | 2025-07-15 | 10:23:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| - | 2025-07-16 | 10:20:00 | S | Ebenezar | male | Tamil Nadu | 06:00 |
| - | 2025-07-17 | 10:06:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| - | 2025-07-18 | 10:08:00 | S | Ebenezar | male | Tamil Nadu | 06:00 |
| 13:15:00 | 2025-07-19 | 10:27:00 | S | Ebenezar | male | Tamil Nadu | 06:00 |
| 19:45:00 | 2025-07-22 | 10:09:00 | S | Ebenezar | male | Tamil Nadu | 01:26 |
| 19:17:00 | 2025-07-25 | 10:04:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:22:00 | 2025-07-28 | 09:46:00 | S | Ebenezar | male | Tamil Nadu | 01:07 |
| 19:10:00 | 2025-12-02 | 10:20:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:04:00 | 2025-08-05 | 10:00:00 | S | Ebenezar | male | Tamil Nadu | 00:54 |
| - | 2025-08-06 | 10:34:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| - | 2025-08-07 | 10:09:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| - | 2025-08-08 | 10:24:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:35:00 | 2025-08-19 | 10:09:00 | S | Ebenezar | male | Tamil Nadu | 01:16 |
| 19:10:00 | 2025-08-14 | 10:20:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:10:00 | 2025-08-13 | 10:20:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:10:00 | 2025-08-09 | 10:20:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:30:00 | 2025-08-11 | 10:00:00 | S | Ebenezar | male | Tamil Nadu | 01:20 |
| 19:10:00 | 2025-08-12 | 10:10:00 | S | Ebenezar | male | Tamil Nadu | 00:50 |
| 19:10:00 | 2025-08-18 | 10:20:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| - | 2025-09-02 | 10:05:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:35:00 | 2025-08-20 | 10:10:00 | S | Ebenezar | male | Tamil Nadu | 01:15 |
| 19:43:00 | 2025-08-21 | 10:16:00 | S | Ebenezar | male | Tamil Nadu | 01:17 |
| 19:21:00 | 2025-08-22 | 10:22:00 | S | Ebenezar | male | Tamil Nadu | 00:49 |
| 19:10:00 | 2025-08-23 | 10:29:00 | S | Ebenezar | male | Tamil Nadu | 00:31 |
| 19:40:00 | 2025-08-26 | 10:12:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:10:00 | 2025-08-25 | 10:20:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| - | 2025-08-28 | 10:21:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:32:00 | 2025-09-16 | 10:21:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 18:40:00 | 2025-09-18 | 10:19:00 | S | Ebenezar | male | Tamil Nadu | 00:11 |
| 18:05:00 | 2025-09-03 | 10:21:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:00:00 | 2025-09-04 | 10:17:00 | S | Ebenezar | male | Tamil Nadu | 00:33 |
| 19:31:00 | 2025-09-05 | 10:30:00 | S | Ebenezar | male | Tamil Nadu | 00:51 |
| 19:19:00 | 2025-09-06 | 10:26:00 | S | Ebenezar | male | Tamil Nadu | 00:00 |
| 19:50:00 | 2025-09-17 | 10:16:00 | S | Ebenezar | male | Tamil Nadu | 00:16 |
| 18:36:00 | 2025-09-08 | 10:10:00 | S | Ebenezar | male | Tamil Nadu | 00:16 |
| 19:11:00 | 2025-09-09 | 10:17:00 | S | Ebenezar | male | Tamil Nadu | 00:44 |

*Showing first 50 of 100 records.*
```

### Q: If multiple employees have the same first name, identify the correct employee using last name and badge ID before retrieving attendance.
- **Status**: ❌ FAILED
- **Time**: 28.60s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: What attendance records belong to employee ID <employee_id>?
- **Status**: ✅ PASSED
- **Time**: 18.90s
- **Database Rows Processed**: 100
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
| Attendance Clock Out | Attendance Date | Attendance Clock In | Employee Last Name | Employee First Name | Badge Id |
| --- | --- | --- | --- | --- | --- |
| 19:31:00 | 2025-06-30 | 17:51:00 | P | Ramana | 48 |
| 19:32:00 | 2025-06-30 | 17:51:00 | N | Suriyakumar | 33 |
| 19:32:00 | 2025-06-30 | 17:39:00 | D | Rajagopal | 50 |
| 19:38:00 | 2025-06-30 | 19:38:00 | S | Ebenezar | 9 |
| 19:38:00 | 2025-06-30 | 17:54:00 | S | Kavin | 56 |
| 19:42:00 | 2025-06-30 | 18:12:00 | Vedium | Karthik | 24 |
| 19:42:00 | 2025-06-30 | 18:12:00 | T | SIVAGNANAM | 53 |
| 19:44:00 | 2025-06-30 | 17:54:00 | P | Kannan | 57 |
| 19:45:00 | 2025-06-30 | 17:51:00 | M | SivaRaj | 30 |
| 19:46:00 | 2025-06-30 | 18:01:00 | E | jeeva | 51 |
| 19:49:00 | 2025-06-30 | 17:54:00 | N.S | Praveen | 22 |
| 19:49:00 | 2025-06-30 | 17:51:00 | M | Manoj Kumar | 29 |
| 19:50:00 | 2025-06-30 | 18:01:00 | R | Gokul | 46 |
| 19:51:00 | 2025-06-30 | 17:49:00 | - | Prakash | 65 |
| 19:54:00 | 2025-06-30 | 18:01:00 | S | Tamilarasan | 52 |
| 19:54:00 | 2025-06-30 | 17:39:00 | S | Sanjay | 64 |
| 19:55:00 | 2025-06-30 | 17:52:00 | M | Vimal Kumar | 7 |
| 19:56:00 | 2025-06-30 | 17:53:00 | M | Alameen | 54 |
| 20:01:00 | 2025-06-30 | 18:01:00 | R | Kathiravan | 49 |
| 17:23:00 | 2025-07-01 | 09:24:00 | S | Kavin | 56 |
| - | 2025-06-30 | 18:04:00 | Kannan M | Rajesh | 1 |
| - | 2025-07-07 | 08:51:00 | S | Gomathi | 42 |
| - | 2025-07-29 | 08:27:00 | S | Gomathi | 42 |
| - | 2025-07-01 | 10:49:00 | D | Rajagopal | 50 |
| 17:12:00 | 2025-07-01 | 10:18:00 | N | Suriyakumar | 33 |
| 17:27:00 | 2025-07-01 | 10:06:00 | M | Alameen | 54 |
| 17:17:00 | 2025-07-01 | 10:09:00 | N.S | Praveen | 22 |
| 17:22:00 | 2025-07-01 | 10:12:00 | P | Kannan | 57 |
| 17:17:00 | 2025-07-01 | 09:38:00 | M | SivaRaj | 30 |
| 17:16:00 | 2025-07-01 | 10:35:00 | M | Manoj Kumar | 29 |
| 19:46:00 | 2025-07-01 | 09:38:00 | Vedium | Karthik | 24 |
| 17:07:00 | 2025-07-01 | 09:36:00 | - | Prakash | 65 |
| 17:12:00 | 2025-07-01 | 12:32:00 | S | Tamilarasan | 52 |
| 13:55:00 | 2025-07-01 | 10:02:00 | R S | Ram Kumar | 59 |
| 19:54:00 | 2025-07-01 | 09:49:00 | S | Sanjay | 64 |
| 18:15:00 | 2025-07-01 | 10:28:00 | R | Kathiravan | 49 |
| 17:18:00 | 2025-07-01 | 09:55:00 | M | Gunalan | 60 |
| 17:22:00 | 2025-07-01 | 10:20:00 | M | Vimal Kumar | 7 |
| 17:04:00 | 2025-07-01 | 09:46:00 | R | Jeevitha | 31 |
| 17:11:00 | 2025-07-01 | 10:21:00 | E | jeeva | 51 |
| 17:35:00 | 2025-07-01 | 10:00:00 | P | Ramana | 48 |
| 17:04:00 | 2025-07-01 | 09:46:00 | R | Sheeladevi | 61 |
| 17:32:00 | 2025-07-01 | 10:19:00 | S | Sathyanarayanan | 55 |
| 17:24:00 | 2025-07-02 | 09:17:00 | S | Kavin | 56 |
| 18:30:00 | 2025-07-02 | 09:00:00 | R | Thiru Murugan | 21 |
| 19:11:00 | 2025-07-02 | 09:22:00 | S | Muthujayavardhini | 38 |
| 13:22:00 | 2025-07-02 | 10:15:00 | N.S | Praveen | 22 |
| 13:06:00 | 2025-07-02 | 09:55:00 | R | Jeevitha | 31 |
| 14:18:00 | 2025-07-01 | 09:53:00 | Kannan M | Rajesh | 1 |
| 16:53:00 | 2025-07-01 | 08:48:00 | T | SIVAGNANAM | 53 |

*Showing first 50 of 100 records.*
```

### Q: Retrieve the biometric/attendance history of Ebenezar S for a particular date range.
- **Status**: ❌ FAILED
- **Time**: 9.16s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: Who worked the most hours on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 1.23s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Id**: 118
- **Attendance Date**: 2026-09-01
```

### Q: Which employee worked the least amount of time on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 7.06s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Id**: 68
- **Created At**: 2026-09-01T03:35:26.087146+00:00
- **Is Active**: True
- **Attendance Date**: 2026-09-01
- **Attendance Clock In Date**: 2026-09-01
- **Attendance Clock In**: 08:50:49
- **Attendance Clock Out Date**: N/A
- **Attendance Clock Out**: N/A
- **Attendance Worked Hour**: 00:00
- **Minimum Hour**: 08:10
- **Attendance Overtime**: 00:00
- **Attendance Overtime Approve**: False
- **Attendance Validated**: False
- **At Work Second**: 0
- **Overtime Second**: 0
- **Approved Overtime Second**: 0
- **Is Validate Request**: False
- **Is Bulk Request**: False
- **Is Validate Request Approved**: False
- **Request Description**: N/A
- **Request Type**: update_request
- **Is Holiday**: False
- **Requested Data**: N/A
- **Attendance Day Id**: 2
- **Batch Attendance Id Id**: N/A
- **Created By Id**: N/A
- **Employee Id Id**: 68
- **Modified By Id**: N/A
- **Shift Id Id**: 2
- **Work Type Id Id**: 2
- **Modified Time**: N/A
- **Badge Id**: 42
- **Employee First Name**: Gomathi
- **Employee Last Name**: S
- **Employee Profile**: 
- **Email**: empty@gmail.com
- **Phone**: 9791069583
- **Address**: 
- **Country**: N/A
- **State**: N/A
- **City**: N/A
- **Zip**: N/A
- **Dob**: N/A
- **Gender**: female
- **Qualification**: N/A
- **Experience**: N/A
- **Marital Status**: single
- **Children**: N/A
- **Emergency Contact**: N/A
- **Emergency Contact Name**: N/A
- **Emergency Contact Relation**: N/A
- **Additional Info**: N/A
- **Is From Onboarding**: False
- **Is Directly Converted**: False
- **Employee User Id Id**: 68
```

### Q: Rank all employees by total working hours on 2026-09-01.
- **Status**: ❌ FAILED
- **Time**: 3.58s
- **Database Rows Processed**: 1
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
The total is None.
```

### Q: Which employees worked more than 8 hours on 2026-09-01?
- **Status**: ❌ FAILED
- **Time**: 3.57s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: Which employees worked less than 6 hours on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 3.58s
- **Database Rows Processed**: 2
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
| At Work Second | Attendance Date | Attendance Clock In | Attendance Clock Out | Attendance Worked Hour | Employee Last Name | Employee First Name |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 2026-09-01 | 08:50:49 | - | 00:00 | S | Gomathi |
| 19740 | 2026-09-01 | 14:26:23 | 19:55:40 | 05:29 | S | Bhuvankumar |

**Summary:** Total At Work Second: 19740
```

### Q: What is the average working time of all employees on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 7.82s
- **Database Rows Processed**: 43
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
| Id | Created At | Is Active | Attendance Date | Attendance Clock In Date | Attendance Clock In | Attendance Clock Out Date | Attendance Clock Out | Attendance Worked Hour | Minimum Hour | Attendance Overtime | Attendance Overtime Approve | Attendance Validated | At Work Second | Overtime Second | Approved Overtime Second | Is Validate Request | Is Bulk Request | Is Validate Request Approved | Request Description | Request Type | Is Holiday | Requested Data | Attendance Day Id | Batch Attendance Id Id | Created By Id | Employee Id Id | Modified By Id | Shift Id Id | Work Type Id Id | Modified Time | Id | Badge Id | Employee First Name | Employee Last Name | Employee Profile | Email | Phone | Address | Country | State | City | Zip | Dob | Gender | Qualification | Experience | Marital Status | Children | Emergency Contact | Emergency Contact Name | Emergency Contact Relation | Is Active | Additional Info | Is From Onboarding | Is Directly Converted | Employee User Id Id |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 68 | 2026-09-01T03:35:26.087146+00:00 | True | 2026-09-01 | 2026-09-01 | 08:50:49 | - | - | 00:00 | 08:10 | 00:00 | False | False | 0 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 68 | - | 2 | 2 | - | 68 | 42 | Gomathi | S |  | empty@gmail.com | 9791069583 |  | - | - | - | - | - | female | - | - | single | - | - | - | - | True | - | False | False | 68 |
| 58 | 2026-09-01T04:15:25.874652+00:00 | True | 2026-09-01 | 2026-09-01 | 09:29:47 | 2026-09-01 | 18:07:43 | 08:23 | 08:10 | 00:13 | False | True | 30180 | 780 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 58 | - | 2 | 2 | 2026-09-01T12:56:01.875348+00:00 | 58 | 55 | Sathyanarayanan | S |  | sathyanarayan@gramosoft.in | +919345763548 | No 52/43,Vanniyar Street,Pernamallur Post,Vanthavasi TK,Thiruvannamalai (Dt)-604503 | India | Tamil Nadu | Vandarloor | 600048 | 2002-05-09 | male | BE, CSE | - | single | - | 9677532906 | Aruldevi | Mother | True | - | False | False | 58 |
| 114 | 2026-09-01T04:35:26.766348+00:00 | True | 2026-09-01 | 2026-09-01 | 09:48:55 | 2026-09-01 | 18:00:08 | 08:12 | 08:10 | 00:02 | False | True | 29520 | 120 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 114 | - | 2 | 2 | 2026-09-01T12:36:10.485537+00:00 | 114 | 94 | Akshay Kumar | L |  | l.akshaykumar2108@gmail.com | 7010201515 | No 32, Ballard Street, Punitham Flats, Agaram, Chennai - 82 | India | Tamil Nadu | Chennai | 600082 | 1999-08-21 | male | Masters in Business Administration (MBA) | 3 | married | 0 | Lalith Kumar | 9840937751 | Father | True | - | False | False | 115 |
| 112 | 2026-09-01T04:55:30.478451+00:00 | True | 2026-09-01 | 2026-09-01 | 10:13:42 | 2026-09-01 | 19:51:14 | 08:43 | 00:00 | 06:00 | False | True | 31380 | 21600 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 112 | - | - | - | 2026-09-01T14:36:10.618513+00:00 | 112 | 92 | Santhosh | M | employee/employee/employee_profile/santhosh-court-shoot-ps-086fc97a.png | santhosh473abi@gmail.com | 7539941810 | Kudiyana Street(1/59-A), Mananthakudi-Ayyanpettai, Nannilam Tk, Tiruvarur District - 609503, Tamil Nadu. | India | Tamil Nadu | tiruvarur | 609503 | 2004-06-01 | male | BE - CSE | 0 | single | - | 9788508946 | Megala | Mother | True | - | False | False | 113 |
| 52 | 2026-09-01T04:56:06.870946+00:00 | True | 2026-09-01 | 2026-09-01 | 10:26:06.506856 | 2026-09-01 | 18:52:11.319483 | 08:26 | 08:10 | 00:16 | False | True | 30360 | 960 | 0 | False | False | False | - | update_request | False | - | 2 | - | 52 | 52 | 52 | 2 | 2 | 2026-09-01T13:22:11.864594+00:00 | 52 | 10 | Ragu | S |  | ragus@gramosoft.in | 7397365937 | 96, Ananthapuram,Bypass Manamadurai. Sivagangai District (630606). | India | Tamil Nadu | Sivagangai | 630606 | 1998-05-31 | male | B.Tech CSE | - | single | - | 6383762401 | - | Mother | True | - | False | False | 52 |
| 55 | 2026-09-01T04:55:28.844025+00:00 | True | 2026-09-01 | 2026-09-01 | 10:12:20 | 2026-09-01 | 20:08:02 | 09:38 | 08:10 | 01:28 | False | True | 34680 | 5280 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 55 | - | 2 | 2 | 2026-09-01T14:56:07.730321+00:00 | 55 | 59 | Ram Kumar | R S |  | ramkumarrs@gramosoft.in | 9566824244 | N0 29 Dhanalakshmi Street Bus Stand Back side Tiruvallur 602001 | India | Tamil Nadu | Tiruvallur | 602001 | 2001-12-02 | male | - | - | single | - | 7904280028 | lokesh | Brother | True | - | False | False | 55 |
| 87 | 2026-09-01T03:55:25.968752+00:00 | True | 2026-09-01 | 2026-09-01 | 09:13:01 | 2026-09-01 | 18:01:03 | 08:26 | 08:10 | 00:16 | False | True | 30360 | 960 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 87 | - | 2 | 2 | 2026-09-01T12:36:13.195846+00:00 | 87 | 1029 | HR | - |  | hr@gramosoft.in | +919848827719 | 2nd Floor, SSD Oil Mill Road, A.N. Elumalai Salai, VGN Nagar, Iyyappanthangal, Chennai, Tamil Nadu | India | Tamil Nadu | Chennai | 600056 | 1995-01-27 | female | - | - | single | - | - | - | - | True | - | False | False | 88 |
| 116 | 2026-09-01T04:55:28.296028+00:00 | True | 2026-09-01 | 2026-09-01 | 10:09:57 | 2026-09-01 | 19:59:19 | 09:34 | 08:10 | 01:24 | False | True | 34440 | 5040 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 116 | - | 2 | 2 | 2026-09-01T14:36:38.022205+00:00 | 116 | 95 | Hemanth | B |  | hemanth310304@gmail.com | 8667451650 | 5/809 , VOC 3rd street,Thasildhar Nagar, Madurai-20. | India | Tamil Nadu | Madurai | 625020 | 2004-03-31 | male | BE | - | single | - | 9952816412 | Baskaran K | Father | True | - | False | False | 117 |
| 64 | 2026-09-01T04:55:29.496014+00:00 | True | 2026-09-01 | 2026-09-01 | 10:12:22 | 2026-09-01 | 20:01:40 | 09:27 | 08:10 | 01:17 | False | True | 34020 | 4620 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 64 | - | 2 | 2 | 2026-09-01T14:36:44.315350+00:00 | 64 | 58 | Vinothkumar | S |  | vinothkumar.s@gramosoft.in | +919551513906 | No 75/4, 5th Street, Eb Office, Vel Nagar, Maduravoyal Post, Ambattur, Tiruvallur, Tamil Nadu, 600095, | India | Tamil Nadu | Maduravoyal | 600095 | 2004-04-22 | male | B.com (accounting & finance) | - | single | - | 9940479583 | - | Brother | True | - | False | False | 64 |
| 101 | 2026-09-01T04:55:34.944052+00:00 | True | 2026-09-01 | 2026-09-01 | 10:20:48 | 2026-09-01 | 20:01:38 | 06:44 | 08:10 | 00:00 | False | True | 24240 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 101 | - | 2 | 2 | 2026-09-01T14:36:42.224515+00:00 | 101 | 82 | Elakkiya | B |  | elakiyabaskar2005@gmail.com | 6369895356 | 78 7 th street ambal nagar balaji anuve | India | Tamil Nadu | Mangadu | 600122 | 2005-12-13 | female | B.SC Computer Science | 0 | single | 0 | 9094397125 | G.Baskaran | Father | True | - | False | False | 102 |
| 94 | 2026-09-01T04:35:27.767219+00:00 | True | 2026-09-01 | 2026-09-01 | 09:52:06 | 2026-09-01 | 19:59:14 | 09:45 | 00:00 | 06:00 | False | True | 35100 | 21600 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 94 | - | 1 | 2 | 2026-09-01T14:36:35.794856+00:00 | 94 | 80 | Prabhu | K |  | prabhuprabhu3330@gmail.com | 9092903819 | No.15 Pillaiyar Kovil Street, Andalkuppam, Kundrathur | India | Tamil Nadu | Chennai | 600069 | 2003-03-25 | male | BCA | 1 | single | 0 | 6379530086 | Sindhu | Sister | True | - | False | False | 95 |
| 104 | 2026-09-01T04:55:27.277905+00:00 | True | 2026-09-01 | 2026-09-01 | 10:06:06 | 2026-09-01 | 19:57:22 | 09:31 | 08:10 | 01:21 | False | True | 34260 | 4860 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 104 | - | 2 | 2 | 2026-09-01T14:36:23.294207+00:00 | 104 | 86 | Dhanush | R |  | dhanushr@gramosoft.in | 6383503048 | New No 12, Old No 17, Pillaiyar kovil street, Vadapalani Chennai - 600026 | India | Tamil Nadu | Chennai | - | 2003-03-21 | male | B.E. COMPUTER SCIRENCE ENGINEERING | - | single | - | 9840734550 | Rajendran | Father | True | - | False | False | 105 |
| 95 | 2026-09-01T05:15:26.320883+00:00 | True | 2026-09-01 | 2026-09-01 | 10:25:08 | 2026-09-01 | 19:31:14 | 08:11 | 08:10 | 00:01 | False | True | 29460 | 60 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 95 | - | 2 | 2 | 2026-09-01T14:16:13.646659+00:00 | 95 | 81 | Shivapriya | D |  | shivapriya3034@gmail.com | 8220308142 | Plot no: 71, 2nd street, Subbiah Nagar, Iyyappanthangal, Chennai. | India | Tamil Nadu | Chennai | 600056 | 2001-11-01 | female | B.E - CSE | 0 | married | 0 | 8072175976 | Tamilalagan | Husband | True | - | False | False | 96 |
| 39 | 2026-09-01T04:35:26.260791+00:00 | True | 2026-09-01 | 2026-09-01 | 09:45:17 | 2026-09-01 | 19:58:23 | 09:58 | 08:10 | 01:48 | False | True | 35880 | 6480 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 39 | - | 2 | 2 | 2026-09-01T14:36:33.705330+00:00 | 39 | 9 | Ebenezar | S |  | ebenezars@gramosoft.in | +918838913541 | 183, Sandapettai Street, Srivilliputhur - 626125. | India | Tamil Nadu | Srivilliputhur | 626125. | 1999-07-29 | male | Bsc IT | - | single | - | 7387672230 | Rachel | Sister | True | - | False | False | 39 |
| 79 | 2026-09-01T04:55:32.598474+00:00 | True | 2026-09-01 | 2026-09-01 | 10:16:51 | 2026-09-01 | 19:52:11 | 08:23 | 08:10 | 00:13 | False | True | 30180 | 780 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 79 | - | 2 | 2 | 2026-09-01T14:36:17.030756+00:00 | 79 | 70 | Ramkumar | S |  | ramkumars@gramosoft.in | 9597466893 | 3/221-1 Rajiv Nagar, Lakshmipuram, Tenkasi -627861 | India | Tamil Nadu | Tenkasi | 627861 | 2004-05-20 | male | BE, ECE | - | single | - | 8220865044 | Sudalaikasi | Father | True | - | False | False | 80 |
| 98 | 2026-09-01T04:55:35.929307+00:00 | True | 2026-09-01 | 2026-09-01 | 10:22:36 | 2026-09-01 | 19:58:03 | 08:28 | 08:10 | 00:18 | False | True | 30480 | 1080 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 98 | - | 2 | 2 | 2026-09-01T14:36:29.537962+00:00 | 98 | 203 | Girinath | R |  | rgirinathramamurthy@gmail.com | 8072050170 | 11, Vivekananda Nagar Main Rd, Rajiv Gandhi Nagar, Jayanthi Nagar, Lakshmipuram, Chennai, Tamil Nadu 600099 | India | Tamil Nadu | Chennai | 600099 | 2001-07-18 | male | M.Sc Computer Science | 3 | single | - | 9176216782 | K.Ramamurhy | Father | True | - | False | False | 99 |
| 44 | 2026-09-01T04:55:26.184370+00:00 | True | 2026-09-01 | 2026-09-01 | 10:06:02 | 2026-09-01 | 20:46:06 | 10:13 | 08:10 | 02:03 | False | True | 36780 | 7380 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 44 | 88 | 2 | 2 | 2026-09-03T04:14:29.502492+00:00 | 44 | 24 | Karthik | Vedium |  | vediumkarthik@gmail.com | 8977741931 | 17/58 Vinobhanagar Village, Nagalapuram, Tirupathi 517589 | India | Andhra Pradesh | Tirupathi | 517589 | 1992-06-05 | male | MBA | - | single | - | 9491522394 | Kamal | Brother | True | - | False | False | 44 |
| 41 | 2026-09-01T04:55:35.431849+00:00 | True | 2026-09-01 | 2026-09-01 | 10:22:32 | 2026-09-01 | 19:25:05 | 08:31 | 08:10 | 00:21 | False | True | 30660 | 1260 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 41 | - | 2 | 2 | 2026-09-01T13:57:26.479566+00:00 | 41 | 60 | Gunalan | M |  | gunalanm@gramosoft.in | 9025874717 | Thoppu street,ramanujam nagar,papanasam tk,thanjavur dt-614209 | India | Tamil Nadu | Papanasam | 614209 | 2002-10-27 | male | BE | - | single | - | 7639284435 | Murugandham | Father | True | - | False | False | 41 |
| 38 | 2026-09-01T04:55:33.963501+00:00 | True | 2026-09-01 | 2026-09-01 | 10:17:37 | 2026-09-01 | 19:57:24 | 08:44 | 08:10 | 00:34 | False | True | 31440 | 2040 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 38 | - | 2 | 2 | 2026-09-01T14:36:25.367341+00:00 | 38 | 27 | Duraisingh | S |  | durais@gramosoft.in | +916374351293 | 256/B, West Street, Pattraburam, Nanguneri (TK), Tirunelveli - 627108. | India | Tamil Nadu | Tirunelveli | 627108 | 2000-09-13 | male | - | - | single | - | 9486248450 | - | Mother | True | - | False | False | 38 |
| 103 | 2026-09-01T04:35:27.265597+00:00 | True | 2026-09-01 | 2026-09-01 | 09:51:15 | 2026-09-01 | 19:50:17 | 09:41 | 08:10 | 01:31 | False | True | 34860 | 5460 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 103 | - | 2 | 2 | 2026-09-01T14:36:06.724318+00:00 | 103 | 85 | Rathish | R |  | rathishreb4@gmail.com | 8825974996 | 6/103 , Kurinji Nagar , Siruvachur , Thalaivasal taluk , Salem District - 636112 | India | Tamil Nadu | Salem | 636112 | 2004-03-09 | male | B.E - Cyber Security | - | single | - | 6382315637 | Ravikumar K | 9894058816 | True | - | False | False | 104 |
| 105 | 2026-09-01T04:55:34.454800+00:00 | True | 2026-09-01 | 2026-09-01 | 10:18:55 | 2026-09-01 | 19:53:00 | 08:36 | 08:10 | 00:26 | False | True | 30960 | 1560 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 105 | - | 2 | 2 | 2026-09-01T14:36:19.117508+00:00 | 105 | 87 | Kabilan | S |  | kabilansenthil07@gmail.com | 8825856493 | 4/221,perumal kovil street, kallai. olaipadi(po), kunnam(tk), permabalur(dt)-621717. | India | Tamil Nadu | perambalur | 621717 | 2004-12-18 | male | B.Tech Information Technology | 0 | single | - | 9360199917 | Senthil Kumar K | Father | True | - | False | False | 106 |
| 80 | 2026-09-01T04:55:26.692321+00:00 | True | 2026-09-01 | 2026-09-01 | 10:06:05 | 2026-09-01 | 19:26:45 | 08:34 | 08:10 | 00:24 | False | True | 30840 | 1440 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 80 | - | 2 | 2 | 2026-09-01T14:16:09.351201+00:00 | 80 | 71 | Ganeshamoorthi | V |  | ganeshamoorthi@gramosoft.in | 9962376293 | no:791 8th East Street, Methanagar, Kundrathur Chennai-69 | India | Tamil Nadu | Chennai | 600069 | 2003-06-19 | male | BE Computer Science | - | single | - | 9841150475 | Velusamy S | Father | True | - | False | False | 81 |
| 110 | 2026-09-01T04:35:28.777879+00:00 | True | 2026-09-01 | 2026-09-01 | 09:56:59 | 2026-09-01 | 19:29:42 | 08:38 | 08:10 | 00:28 | False | True | 31080 | 1680 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 110 | - | 2 | 2 | 2026-09-01T14:16:11.527354+00:00 | 110 | 91 | Arun | N |  | narunece04@gmail.com | 9677645107 | 12/Gandhi silai street thachanallur tirunelveli pin-code 627358 | India | Tamil Nadu | Tirunelveli | 627358 | 2003-08-04 | male | BE | 0 | single | 0 | 8300025414 | sathya | brother | True | - | False | False | 111 |
| 106 | 2026-09-01T04:35:30.776488+00:00 | True | 2026-09-01 | 2026-09-01 | 10:04:16 | 2026-09-01 | 19:51:45 | 08:44 | 08:10 | 00:34 | False | True | 31440 | 2040 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 106 | - | 2 | 2 | 2026-09-01T14:36:14.790949+00:00 | 106 | 88 | Jagan | M |  | jagan06042004@gmail.com | 6383230433 | Sankarankoil Subdistrict | India | Tamil Nadu | Tenkasi | 627859 | 2004-04-06 | male | BE/ECE | - | single | - | 9487854149 | Mariappan | Father | True | - | False | False | 107 |
| 63 | 2026-09-01T05:15:34.520631+00:00 | True | 2026-09-01 | 2026-09-01 | 10:35:55 | 2026-09-01 | 19:58:05 | 08:08 | 08:10 | 00:00 | False | True | 29280 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 63 | - | 2 | 2 | 2026-09-01T14:36:31.616211+00:00 | 63 | 7 | Vimal Kumar | M |  | vimalkumarm@gramosoft.in | +919159120665 | 4/884 PUS Nagar, Vazhachanur, Thandrapattu, TVM, | India | Tamil Nadu | Thandrapattu | - | 2002-06-10 | male | BE | 3 | single | - | 9443629282 | Muthukumar | Father | True | - | False | False | 63 |
| 102 | 2026-09-01T05:15:28.884438+00:00 | True | 2026-09-01 | 2026-09-01 | 10:28:45 | 2026-09-01 | 20:01:34 | 09:05 | 08:10 | 00:55 | False | True | 32700 | 3300 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 102 | - | 2 | 2 | 2026-09-01T14:36:40.113949+00:00 | 102 | 84 | Mahalakshmi | P |  | mahalekshm.p1989@gmail.com | 6385286889 | 102/2 Middle Street, Mettupirancheri | India | Tamil Nadu | Tirunelveli | 627352 | 2005-06-28 | female | B.Tech | 0 | single | - | 9965002523 | Vasantha P | Amma | True | - | False | False | 103 |
| 1 | 2026-09-01T05:35:26.020860+00:00 | True | 2026-09-01 | 2026-09-01 | 10:58:36 | 2026-09-01 | 20:46:27 | 09:01 | 08:10 | 00:51 | False | True | 32460 | 3060 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 1 | - | 2 | 2 | 2026-09-01T15:35:58.405344+00:00 | 1 | 1 | Rajesh | Kannan M |  | rajesh57.cse@gmail.com | 8148582488 | Iyyappanthangal, Chennai | India | Tamil Nadu | Chennai | - | - | male | - | - | married | 1 | - | - | - | True | - | False | False | 1 |
| 35 | 2026-09-01T05:15:35.995381+00:00 | True | 2026-09-01 | 2026-09-01 | 10:36:04 | 2026-09-01 | 20:46:31 | 08:50 | 08:10 | 00:40 | False | True | 31800 | 2400 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 35 | - | 2 | 2 | 2026-09-01T15:36:00.001325+00:00 | 35 | 54 | Alameen | M | employee/employee/employee_profile/photo-1524f29d.jpg | alameen@gramosoft.in | +919087291830 | 31A/1B, Krishnarajapuram, 6th Street, Tuticorin - 628002 | India | Tamil Nadu | Tuticorin | 628002 | 2002-10-25 | male | B.E - Computer Science and Engineering | 2 | single | 0 | 9488070512 | Muthu Maideen | Father | True | - | False | False | 35 |
| 67 | 2026-09-01T05:15:27.705634+00:00 | True | 2026-09-01 | 2026-09-01 | 10:28:42 | 2026-09-01 | 18:05:37 | 07:09 | 08:10 | 00:00 | False | True | 25740 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 67 | - | 2 | 2 | 2026-09-01T12:37:24.373006+00:00 | 67 | 61 | Sheeladevi | R |  | sheeladevir@gramosoft.in | +91 6381038985 | 2/75a, East street, kannapatti, Dindigul (dist), Nilakkottai (taluk) | India | Tamil Nadu | Chennai | - | 2003-05-06 | female | MCA | - | single | - | +91 93607 43327 | Thirumurugan | Brother | True | - | False | False | 67 |
| 113 | 2026-09-01T04:12:23.144643+00:00 | True | 2026-09-01 | 2026-09-01 | 09:42:22.764429 | 2026-09-01 | 18:38:48.534377 | 08:03 | 08:10 | 00:00 | False | True | 28980 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | 114 | 113 | 114 | 2 | 2 | 2026-09-01T13:08:49.724403+00:00 | 113 | 93 | Karthika | G |  | karthikagomathi08@gmail.com | 9940287948 | No: 98, Srinivas Flat, Sri Krishna Nagar, Mosque street, Noombal, chennai- 77 | India | Tamil Nadu | Chennai | 600 077 | 1993-08-02 | female | B.com | 10 | married | 1 | 9025180684 | Karthik | Husband | True | - | False | False | 114 |
| 117 | 2026-09-01T04:35:28.273510+00:00 | True | 2026-09-01 | 2026-09-01 | 09:53:14 | 2026-09-01 | 19:16:21 | 07:30 | 00:00 | 06:00 | False | True | 27000 | 21600 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 117 | - | - | - | 2026-09-01T13:56:09.759359+00:00 | 117 | 98 | Nanda Gopal | V |  | nandagopal315@gmail.com | 7550167981 /8610276873 | N0: 15/16  , Perumal Kovil street , Thideer Nagar, Maduravoyal | India | Tamil Nadu | chennai | 600095 | 2002-02-06 | male | MSC cyber security | - | single | - | 9790795864 | Damodharan V | BROTHER | True | - | False | False | 118 |
| 78 | 2026-09-01T05:15:30.248300+00:00 | True | 2026-09-01 | 2026-09-01 | 10:29:42 | 2026-09-01 | 19:20:49 | 08:17 | 08:10 | 00:07 | False | True | 29820 | 420 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 78 | - | 2 | 2 | 2026-09-01T13:56:12.955728+00:00 | 78 | 69 | Vignesh | M |  | vignesh@gramosoft.in | 6381849608 | 2/69, North Street , Perumanendhal, Sathani, Ilayangudi, Sivagangai - 630709. | India | Tamil Nadu | Sivagangai | 630709 | 2004-07-19 | male | Bsc IT | - | single | - | 8489737750 | Brother | Vijay | True | - | False | False | 79 |
| 56 | 2026-09-01T05:15:26.832729+00:00 | True | 2026-09-01 | 2026-09-01 | 10:27:52 | 2026-09-01 | 19:23:29 | 08:25 | 08:10 | 00:15 | False | True | 30300 | 900 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 56 | - | 2 | 2 | 2026-09-01T13:56:17.806482+00:00 | 56 | 48 | Ramana | P |  | ramanap@gramosoft.in | 7708390297 | 145/9, R. Pudukkottai, Renganathapuram South, Valayalkaranpudur(P), Krishnarayapuram(TK), Karur - 639108. | India | Tamil Nadu | Karur | 639108 | 2003-07-09 | male | B. Sc, Computer Science | - | single | - | 7708345420 | Yasotha P | Mother | True | - | False | False | 56 |
| 88 | 2026-09-01T05:15:31.777771+00:00 | True | 2026-09-01 | 2026-09-01 | 10:31:44 | 2026-09-01 | 19:26:24 | 08:43 | 08:10 | 00:33 | False | True | 31380 | 1980 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 88 | - | 2 | 2 | 2026-09-01T14:16:06.656995+00:00 | 88 | 204 | Arun Kumar | C |  | arukumarmuthulakshmi7@gmail.com | 6379048036 |  | India | Tamil Nadu | Chennai | 627953 | 2001-04-16 | male | B.sc Computer science | - | single | - | - | - | Mother | True | - | False | False | 89 |
| 107 | 2026-09-01T04:35:29.731603+00:00 | True | 2026-09-01 | 2026-09-01 | 09:59:39 | 2026-09-01 | 19:32:20 | 08:48 | 08:10 | 00:38 | False | True | 31680 | 2280 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 107 | - | 2 | 2 | 2026-09-01T14:16:15.808316+00:00 | 107 | 89 | Vimal Kumar | S |  | lamiv7551@gmail.com | 7695935979 |  | - | - | - | - | 2002-11-28 | male | - | - | single | - | - | - | - | True | - | False | False | 108 |
| 115 | 2026-09-01T04:55:27.791965+00:00 | True | 2026-09-01 | 2026-09-01 | 10:09:50 | 2026-09-01 | 19:38:15 | 08:39 | 08:10 | 00:29 | False | True | 31140 | 1740 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 115 | - | 2 | 2 | 2026-09-01T14:16:18.069531+00:00 | 115 | 96 | Sikkandhar Rajaak | S |  | sikkandharrajaak.s@gmail.com | 7010358099 |  | - | - | - | - | 2004-09-15 | male | - | - | single | - | - | - | - | True | - | False | False | 116 |
| 60 | 2026-09-01T04:55:33.472190+00:00 | True | 2026-09-01 | 2026-09-01 | 10:16:54 | 2026-09-01 | 19:50:58 | 08:08 | 08:10 | 00:00 | False | True | 29280 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 60 | - | 2 | 2 | 2026-09-01T14:36:08.542507+00:00 | 60 | 33 | Suriyakumar | N |  | suriyakumarn@gramosoft.in | +917010199142 | "Siruvandal, Karkathakudi, Thiruvadanai, Ramnad - 623538." | India | Tamil Nadu | Thiruvadanai | 623538 | 2000-06-20 | male | BE ECE | - | single | - | 90471268476 | Athi | Bother-in-law | True | - | False | False | 60 |
| 59 | 2026-09-01T04:55:31.607481+00:00 | True | 2026-09-01 | 2026-09-01 | 10:16:50 | 2026-09-01 | 19:51:42 | 09:02 | 08:10 | 00:52 | False | True | 32520 | 3120 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 59 | - | 2 | 2 | 2026-09-01T14:36:12.691987+00:00 | 59 | 30 | SivaRaj | M |  | sivaraj.m132002@gmail.com | +917339550982 | 3/205, Sivaji Nagar, Sengamalanachiyar Puram, Namaskarittanpatti, Virudhunagar -626130 | India | Tamil Nadu | Virudhunagar | 626130 | 2002-10-13 | male | Bsc Computer | - | single | - | 8124416108 | Tamilselvi | Mother | True | - | False | False | 59 |
| 36 | 2026-09-01T09:37:58.939182+00:00 | True | 2026-09-01 | 2026-09-01 | 14:26:23 | 2026-09-01 | 19:55:40 | 05:29 | 08:10 | 00:00 | False | True | 19740 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 36 | - | 2 | 2 | 2026-09-01T14:36:21.201524+00:00 | 36 | 36 | Bhuvankumar | S |  | bhuvankumars@gramosoft.in | 9940479583 | No 75/4, 5th Street, Eb Office, Vel Nagar, Maduravoyal Post, Ambattur, Tiruvallur, Tamil Nadu, 600095, | India | Tamil Nadu | Ambattur | 600095 | 2002-09-09 | male | B.sc(cs) | 3 | single | - | +91 95515 13906 | Vinothkumar | Brother | True | - | False | False | 36 |
| 83 | 2026-09-01T05:15:33.161490+00:00 | True | 2026-09-01 | 2026-09-01 | 10:31:47 | 2026-09-01 | 17:38:21 | 06:47 | 08:10 | 00:00 | False | True | 24420 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 83 | - | 2 | 2 | 2026-09-01T14:36:27.413509+00:00 | 83 | 74 | Sri Vishnu | S |  | ssrivishnu002@gmail.com | 7904677821 | 18 No First floor Muthiyal Street | India | Tamil Nadu | chennai | 600016 | 2002-06-03 | male | BCA | - | single | - | 9840069576 | Padhmavathi S | Mother | True | - | False | True | 84 |
| 69 | 2026-09-05T06:53:42.846004+00:00 | True | 2026-09-01 | 2026-09-01 | 10:20:00 | 2026-09-01 | 19:20:00 | 09:00 | 00:00 | 06:00 | False | True | 32400 | 21600 | 0 | False | True | True | - | create_request | False | - | 2 | - | 69 | 69 | 88 | 2 | 2 | 2026-09-05T08:39:16.838415+00:00 | 69 | 63 | Misfar | Ahamed |  | misfarahamedm@gramosoft.in | 6382434855 | 255-DA/15G-A5, Metu Street, Thillai Nagar,2nd Cross, Perambular-621212 | India | Tamil Nadu | Chennai | 621212 | 2025-06-16 | male | BE Mech | 1 | single | - | 7868817010 | Mohammed Gani | Father | True | - | False | False | 69 |
| 65 | 2026-09-05T06:47:03.323535+00:00 | True | 2026-09-01 | 2026-09-01 | 10:20:00 | 2026-09-01 | 19:10:00 | 08:10 | 08:10 | 00:00 | False | True | 29400 | 0 | 0 | False | False | True | - | create_request | False | - | 2 | - | 65 | 65 | 88 | 2 | 5 | 2026-09-05T08:39:18.068498+00:00 | 65 | 51 | jeeva | E |  | jeevae@gramosoft.in | +917358306150 | 1584, Janaki Nagar, 2nd Cross Street, Kattupakkam, Chennai - 600056. | India | Tamil Nadu | Chennai | 600056 | 2000-06-20 | male | MCA | - | single | - | 8056043083 | Loganayaki | Mother | True | - | False | False | 65 |
| 118 | 2026-09-15T06:42:08.377305+00:00 | True | 2026-09-01 | 2026-09-01 | 10:00:00 | 2026-09-01 | 18:10:00 | 08:10 | 00:00 | 06:00 | False | True | 29400 | 21600 | 0 | False | True | True | - | create_request | False | - | 2 | - | 88 | 118 | 88 | 2 | - | 2026-09-15T06:42:36.743290+00:00 | 118 | 99 | Karthik | S |  | karthik7122005@gmail.com | 9791259938 |  | - | - | - | - | 2026-09-01 | male | - | - | single | - | - | - | - | True | - | False | False | 119 |

**Summary:** Total At Work Second: 1292040, Total Overtime Second: 181080, Total Approved Overtime Second: 0, Total Phone: 9436970112454, Total Experience: 26, Total Children: 2, Total Emergency Contact: 370078949228, Total Emergency Contact Name: 9840937751, Total Emergency Contact Relation: 9894058816
```

### Q: How many employees were present on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 3.23s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total count is 0.
```

### Q: Which employee had the earliest clock-in on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 4.92s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Date**: 2026-09-01
- **Attendance Clock In**: 08:50:49
- **Employee Last Name**: S
- **Employee First Name**: Gomathi
- **Attendance Overtime**: 00:00
```

### Q: Which employee had the latest clock-out on 2026-09-01?
- **Status**: ❌ FAILED
- **Time**: 5.01s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: How many total hours did Ebenezar S work between 2026-09-01 and 2026-09-15?
- **Status**: ❌ FAILED
- **Time**: 1.58s
- **Database Rows Processed**: 1
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
The total count is None.
```

### Q: What was Ebenezar S's average daily working time between 2026-09-01 and 2026-09-15?
- **Status**: ❌ FAILED
- **Time**: 1.94s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: How many attendance days did Ebenezar S have between 2026-09-01 and 2026-09-15?
- **Status**: ✅ PASSED
- **Time**: 2.13s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total count is 0.
```

### Q: What was Ebenezar S's maximum daily working time during this period?
- **Status**: ✅ PASSED
- **Time**: 1.32s
- **Database Rows Processed**: 100
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
| Employee First Name |
| --- |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |

*Showing first 50 of 100 records.*
```

### Q: What was Ebenezar S's minimum daily working time during this period?
- **Status**: ✅ PASSED
- **Time**: 1.26s
- **Database Rows Processed**: 100
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
| Employee First Name |
| --- |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |
| Ebenezar |

*Showing first 50 of 100 records.*
```

### Q: On which date did Ebenezar S work the longest?
- **Status**: ✅ PASSED
- **Time**: 9.08s
- **Database Rows Processed**: 100
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
To determine the date on which Ebenezar S worked the longest, we need to examine the "at_work_second" column in the database result, as it directly represents the duration of work in seconds for each attendance date.

Upon reviewing the data, the maximum value in the "at_work_second" column is 791820 seconds, which corresponds to the attendance date "2025-07-16".

Therefore, Ebenezar S worked the longest on "2025-07-16".
```

### Q: On which date did Ebenezar S work the shortest?
- **Status**: ✅ PASSED
- **Time**: 11.34s
- **Database Rows Processed**: 100
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
To determine the date when Ebenezar S worked the shortest, we need to look for the minimum value in the "at_work_second" column, which represents the duration of work in seconds.

Upon examining the data, there are multiple instances where "at_work_second" is 0, indicating that Ebenezar S did not work on those days or the work duration was not recorded. These dates are: "2025-06-30", "2025-07-07", "2025-07-09", "2025-07-10", "2025-07-11", "2025-07-15", "2025-08-07", and "2025-08-28".

However, if we are looking for the shortest work duration where Ebenezar S actually worked (i.e., "at_work_second" is greater than 0), the smallest non-zero value in the "at_work_second" column is 9300 seconds, which corresponds to the date "2025-08-06".

Therefore, the date when Ebenezar S worked the shortest, considering only the days he actually worked, is "2025-08-06".
```

### Q: Compare Ebenezar S's working hours between two date ranges.
- **Status**: ❌ FAILED
- **Time**: 2.84s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: How much overtime did Ebenezar S work on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 1.47s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total is 6480.
```

### Q: How many overtime hours did Ebenezar S work during September 2026?
- **Status**: ✅ PASSED
- **Time**: 1.34s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total count is 20220.
```

### Q: On which date did Ebenezar S work the most overtime?
- **Status**: ❌ FAILED
- **Time**: 3.90s
- **Database Rows Processed**: 0
- **Reasoning**: Execution error: HTTP 422: {"success":false,"message":"Query plan semantic error: Aggregate projections are present alongside scalar columns ['employee_first_name', 'employee_last_name'] without an explicit GROUP BY clause."}
- **Answer**:
```text
ERROR: HTTP 422: {"success":false,"message":"Query plan semantic error: Aggregate projections are present alongside scalar columns ['employee_first_name', 'employee_last_name'] without an explicit GROUP BY clause."}
```

### Q: What was Ebenezar S's total approved overtime during September 2026?
- **Status**: ✅ PASSED
- **Time**: 1.24s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total is 20220.
```

### Q: Which employees worked more than 10 hours of overtime during September 2026?
- **Status**: ❌ FAILED
- **Time**: 4.56s
- **Database Rows Processed**: 0
- **Reasoning**: Execution error: HTTP 500: {"success":false,"message":"Query execution failed: invalid input for query argument $1: 10.0 (expected str, got float)"}
- **Answer**:
```text
ERROR: HTTP 500: {"success":false,"message":"Query execution failed: invalid input for query argument $1: 10.0 (expected str, got float)"}
```

### Q: Compare Ebenezar S's regular working hours and overtime hours for September 2026.
- **Status**: ❌ FAILED
- **Time**: 1.74s
- **Database Rows Processed**: 1
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
The total is None.
```

### Q: Which employees forgot to clock out on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 4.12s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Clock Out**: N/A
- **Attendance Date**: 2026-09-01
- **Employee Last Name**: S
- **Employee First Name**: Gomathi
- **Attendance Overtime**: 00:00
```

### Q: Which employees have a clock-in but no clock-out?
- **Status**: ✅ PASSED
- **Time**: 6.29s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Clock Out**: N/A
- **Attendance Date**: 2026-09-16
- **Attendance Clock In**: 08:53:55
- **Employee Last Name**: S
- **Employee First Name**: Gomathi
- **Attendance Overtime**: 00:00
```

### Q: Which employees have a clock-out earlier than their clock-in?
- **Status**: ✅ PASSED
- **Time**: 4.29s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Clock Out**: N/A
- **Attendance Date**: 2026-09-16
- **Attendance Clock In**: 08:53:55
- **Employee Last Name**: S
- **Employee First Name**: Gomathi
- **Attendance Overtime**: 00:00
```

### Q: Which employees have unusually long attendance durations?
- **Status**: ❌ FAILED
- **Time**: 4.42s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: Which employees worked less than their minimum required hours?
- **Status**: ✅ PASSED
- **Time**: 3.52s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The lowest value recorded is -12:41.
```

### Q: Which employees arrived after their scheduled shift start?
- **Status**: ❌ FAILED
- **Time**: 5.24s
- **Database Rows Processed**: 100
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
| Id | Id | Employee Last Name | Employee First Name | State | Employee Shift |
| --- | --- | --- | --- | --- | --- |
| 2 | 2 | Ahamed | Misfar | Tamil Nadu | General |
| 2 | 2 | Ahamed | Misfar | Tamil Nadu | General |
| 2 | 2 | Ahamed | Misfar | Tamil Nadu | General |
| 2 | 2 | Ahamed | Misfar | Tamil Nadu | General |
| 2 | 2 | Ahamed | Misfar | Tamil Nadu | General |
| 2 | 2 | Ahamed | Misfar | Tamil Nadu | General |
| 2 | 2 | M | Vimal Kumar | Tamil Nadu | General |
| 2 | 2 | M | Vimal Kumar | Tamil Nadu | General |
| 2 | 2 | M | Vimal Kumar | Tamil Nadu | General |
| 2 | 2 | M | Vimal Kumar | Tamil Nadu | General |
| 2 | 2 | M | Vimal Kumar | Tamil Nadu | General |
| 2 | 2 | M | Vimal Kumar | Tamil Nadu | General |
| 2 | 2 | R | Sheeladevi | Tamil Nadu | General |
| 2 | 2 | R | Sheeladevi | Tamil Nadu | General |
| 2 | 2 | R | Sheeladevi | Tamil Nadu | General |
| 2 | 2 | R | Sheeladevi | Tamil Nadu | General |
| 2 | 2 | R | Sheeladevi | Tamil Nadu | General |
| 2 | 2 | R | Sheeladevi | Tamil Nadu | General |
| 2 | 2 | S | Muthujayavardhini | Tamil Nadu | General |
| 2 | 2 | S | Muthujayavardhini | Tamil Nadu | General |
| 2 | 2 | S | Muthujayavardhini | Tamil Nadu | General |
| 2 | 2 | S | Muthujayavardhini | Tamil Nadu | General |
| 2 | 2 | S | Muthujayavardhini | Tamil Nadu | General |
| 2 | 2 | S | Muthujayavardhini | Tamil Nadu | General |
| 2 | 2 | T | Ajith | Tamil Nadu | General |
| 2 | 2 | T | Ajith | Tamil Nadu | General |
| 2 | 2 | T | Ajith | Tamil Nadu | General |
| 2 | 2 | T | Ajith | Tamil Nadu | General |
| 2 | 2 | T | Ajith | Tamil Nadu | General |
| 2 | 2 | T | Ajith | Tamil Nadu | General |
| 2 | 2 | R | Dhanush | Tamil Nadu | General |
| 2 | 2 | R | Dhanush | Tamil Nadu | General |
| 2 | 2 | R | Dhanush | Tamil Nadu | General |
| 2 | 2 | R | Dhanush | Tamil Nadu | General |
| 2 | 2 | R | Dhanush | Tamil Nadu | General |
| 2 | 2 | R | Dhanush | Tamil Nadu | General |
| 2 | 2 | S | Ebenezar | Tamil Nadu | General |
| 2 | 2 | S | Ebenezar | Tamil Nadu | General |
| 2 | 2 | S | Ebenezar | Tamil Nadu | General |
| 2 | 2 | S | Ebenezar | Tamil Nadu | General |
| 2 | 2 | S | Ebenezar | Tamil Nadu | General |
| 2 | 2 | S | Ebenezar | Tamil Nadu | General |
| 2 | 2 | M | Alameen | Tamil Nadu | General |
| 2 | 2 | M | Alameen | Tamil Nadu | General |
| 2 | 2 | M | Alameen | Tamil Nadu | General |
| 2 | 2 | M | Alameen | Tamil Nadu | General |
| 2 | 2 | M | Alameen | Tamil Nadu | General |
| 2 | 2 | M | Alameen | Tamil Nadu | General |
| 2 | 2 | - | Prakash | None | General |
| 2 | 2 | - | Prakash | None | General |

*Showing first 50 of 100 records.*
```

### Q: Which employees left before their scheduled shift end?
- **Status**: ✅ PASSED
- **Time**: 5.79s
- **Database Rows Processed**: 100
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
| Id | Id | Id | Employee Last Name | Employee First Name | Gender | Employee Shift |
| --- | --- | --- | --- | --- | --- | --- |
| 53 | 53 | 53 | Kannan M | Rajesh | male | General |
| 65 | 65 | 65 | Kannan M | Rajesh | male | General |
| 127 | 127 | 127 | Kannan M | Rajesh | male | General |
| 206 | 206 | 206 | Kannan M | Rajesh | male | General |
| 155 | 155 | 155 | Kannan M | Rajesh | male | General |
| 307 | 307 | 307 | Kannan M | Rajesh | male | General |
| 251 | 251 | 251 | Kannan M | Rajesh | male | General |
| 316 | 316 | 316 | Kannan M | Rajesh | male | General |
| 425 | 425 | 425 | Kannan M | Rajesh | male | General |
| 392 | 392 | 392 | Kannan M | Rajesh | male | General |
| 523 | 523 | 523 | Kannan M | Rajesh | male | General |
| 474 | 474 | 474 | Kannan M | Rajesh | male | General |
| 557 | 557 | 557 | Kannan M | Rajesh | male | General |
| 602 | 602 | 602 | Kannan M | Rajesh | male | General |
| 651 | 651 | 651 | Kannan M | Rajesh | male | General |
| 704 | 704 | 704 | Kannan M | Rajesh | male | General |
| 53 | 53 | 53 | Kannan M | Rajesh | male | General |
| 65 | 65 | 65 | Kannan M | Rajesh | male | General |
| 127 | 127 | 127 | Kannan M | Rajesh | male | General |
| 206 | 206 | 206 | Kannan M | Rajesh | male | General |
| 155 | 155 | 155 | Kannan M | Rajesh | male | General |
| 307 | 307 | 307 | Kannan M | Rajesh | male | General |
| 251 | 251 | 251 | Kannan M | Rajesh | male | General |
| 316 | 316 | 316 | Kannan M | Rajesh | male | General |
| 425 | 425 | 425 | Kannan M | Rajesh | male | General |
| 392 | 392 | 392 | Kannan M | Rajesh | male | General |
| 523 | 523 | 523 | Kannan M | Rajesh | male | General |
| 474 | 474 | 474 | Kannan M | Rajesh | male | General |
| 557 | 557 | 557 | Kannan M | Rajesh | male | General |
| 602 | 602 | 602 | Kannan M | Rajesh | male | General |
| 651 | 651 | 651 | Kannan M | Rajesh | male | General |
| 704 | 704 | 704 | Kannan M | Rajesh | male | General |
| 53 | 53 | 53 | Kannan M | Rajesh | male | General |
| 65 | 65 | 65 | Kannan M | Rajesh | male | General |
| 127 | 127 | 127 | Kannan M | Rajesh | male | General |
| 206 | 206 | 206 | Kannan M | Rajesh | male | General |
| 155 | 155 | 155 | Kannan M | Rajesh | male | General |
| 307 | 307 | 307 | Kannan M | Rajesh | male | General |
| 251 | 251 | 251 | Kannan M | Rajesh | male | General |
| 316 | 316 | 316 | Kannan M | Rajesh | male | General |
| 425 | 425 | 425 | Kannan M | Rajesh | male | General |
| 392 | 392 | 392 | Kannan M | Rajesh | male | General |
| 523 | 523 | 523 | Kannan M | Rajesh | male | General |
| 474 | 474 | 474 | Kannan M | Rajesh | male | General |
| 557 | 557 | 557 | Kannan M | Rajesh | male | General |
| 602 | 602 | 602 | Kannan M | Rajesh | male | General |
| 651 | 651 | 651 | Kannan M | Rajesh | male | General |
| 704 | 704 | 704 | Kannan M | Rajesh | male | General |
| 53 | 53 | 53 | Kannan M | Rajesh | male | General |
| 65 | 65 | 65 | Kannan M | Rajesh | male | General |

*Showing first 50 of 100 records.*
```

### Q: How many employees had incomplete attendance records on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 4.27s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total count is 0.
```

### Q: Find Ebenezar S's attendance on 2026-09-01 and compare his actual working time with the minimum required working time.
- **Status**: ✅ PASSED
- **Time**: 2.84s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Id**: 16641
- **Badge Id**: 9
- **Employee First Name**: Ebenezar
- **Employee Last Name**: S
- **Employee Profile**: 
- **Email**: ebenezars@gramosoft.in
- **Phone**: +918838913541
- **Address**: 183, Sandapettai Street, Srivilliputhur - 626125.
- **Country**: India
- **State**: Tamil Nadu
- **City**: Srivilliputhur
- **Zip**: 626125.
- **Dob**: 1999-07-29
- **Gender**: male
- **Qualification**: Bsc IT
- **Experience**: N/A
- **Marital Status**: single
- **Children**: N/A
- **Emergency Contact**: 7387672230
- **Emergency Contact Name**: Rachel
- **Emergency Contact Relation**: Sister
- **Is Active**: True
- **Additional Info**: N/A
- **Is From Onboarding**: False
- **Is Directly Converted**: False
- **Employee User Id Id**: 39
- **Created At**: 2026-09-01T04:35:26.260791+00:00
- **Attendance Date**: 2026-09-01
- **Attendance Clock In Date**: 2026-09-01
- **Attendance Clock In**: 09:45:17
- **Attendance Clock Out Date**: 2026-09-01
- **Attendance Clock Out**: 19:58:23
- **Attendance Worked Hour**: 09:58
- **Minimum Hour**: 08:10
- **Attendance Overtime**: 01:48
- **Attendance Overtime Approve**: False
- **Attendance Validated**: True
- **At Work Second**: 35880
- **Overtime Second**: 6480
- **Approved Overtime Second**: 0
- **Is Validate Request**: False
- **Is Bulk Request**: False
- **Is Validate Request Approved**: False
- **Request Description**: N/A
- **Request Type**: update_request
- **Is Holiday**: False
- **Requested Data**: N/A
- **Attendance Day Id**: 2
- **Batch Attendance Id Id**: N/A
- **Created By Id**: N/A
- **Employee Id Id**: 39
- **Modified By Id**: N/A
- **Shift Id Id**: 2
- **Work Type Id Id**: 2
- **Modified Time**: 2026-09-01T14:36:33.705330+00:00
```

### Q: What percentage of the required working day did Ebenezar S complete on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 1.27s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **At Work Second**: 35880
- **Attendance Date**: 2026-09-01
- **Attendance Clock In**: 09:45:17
- **Attendance Clock Out**: 19:58:23
- **Attendance Worked Hour**: 09:58
- **Dob**: 1999-07-29
- **Badge Id**: 9
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Gender**: male
```

### Q: Compare Ebenezar S's attendance with his assigned shift.
- **Status**: ❌ FAILED
- **Time**: 1.66s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: What was Ebenezar S's working time versus his shift's expected working time?
- **Status**: ❌ FAILED
- **Time**: 1.28s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: Did Ebenezar S work overtime on a day when his attendance was below the minimum required hours?
- **Status**: ✅ PASSED
- **Time**: 1.99s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The lowest value recorded is 20220.
```

### Q: Find employees who worked less than their required hours but recorded overtime.
- **Status**: ✅ PASSED
- **Time**: 4.51s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total is 1687680.
```

### Q: Find employees who had attendance records but were marked as being on leave.
- **Status**: ❌ FAILED
- **Time**: 17.48s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: How long was Ebenezar S in the office on September 1st?
- **Status**: ✅ PASSED
- **Time**: 1.39s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Gender**: male
```

### Q: How much time did Ebenezar spend at work that day?
- **Status**: ✅ PASSED
- **Time**: 14.16s
- **Database Rows Processed**: 100
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
To answer the question "How much time did Ebenezar spend at work that day?", we need to clarify that the database result provided contains multiple entries for Ebenezar across different days. Without a specific date mentioned in the question, it's challenging to provide a precise answer for "that day." However, I can guide you through how to find the information for any given day based on the data provided.

Each entry in the database result includes an "attendance_date," "at_work_second," and "attendance_worked_hour" for Ebenezar. If you're looking for the time spent at work on a specific day, you would need to identify the row corresponding to that date and look at either the "at_work_second" or "attendance_worked_hour" column for the duration.

For example, if we consider the first entry:
- "attendance_date": "2025-06-30"
- "at_work_second": 0
- "attendance_worked_hour": "00:00"

This means on June 30, 2025, Ebenezar spent 0 seconds or 0 hours at work.

If you provide a specific date, I can help you find the exact amount of time Ebenezar spent at work on that day based on the data provided.
```

### Q: When did Ebenezar arrive and when did he leave?
- **Status**: ❌ FAILED
- **Time**: 3.88s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: Was Ebenezar present on September 1st?
- **Status**: ✅ PASSED
- **Time**: 1.28s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Gender**: male
```

### Q: How many hours did he spend working that day?
- **Status**: ✅ PASSED
- **Time**: 1.78s
- **Database Rows Processed**: 3
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
| Id | Badge Id | Employee First Name | Employee Last Name | Employee Profile | Email | Phone | Address | Country | State | City | Zip | Dob | Gender | Qualification | Experience | Marital Status | Children | Emergency Contact | Emergency Contact Name | Emergency Contact Relation | Is Active | Additional Info | Is From Onboarding | Is Directly Converted | Employee User Id Id |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 67 | 61 | Sheeladevi | R |  | sheeladevir@gramosoft.in | +91 6381038985 | 2/75a, East street, kannapatti, Dindigul (dist), Nilakkottai (taluk) | India | Tamil Nadu | Chennai | - | 2003-05-06 | female | MCA | - | single | - | +91 93607 43327 | Thirumurugan | Brother | True | - | False | False | 67 |
| 93 | 79 | Pragathees | M |  | admin@gramosoft.in | 9360684343 | illyankundi, thontaiyur | India | Tamil Nadu | Sivagangai | 630702 | 2003-06-24 | male | B.A Tamil | - | single | - | 9788783898 | MUNIYANDI | Father | False | - | False | False | 94 |
| 116 | 95 | Hemanth | B |  | hemanth310304@gmail.com | 8667451650 | 5/809 , VOC 3rd street,Thasildhar Nagar, Madurai-20. | India | Tamil Nadu | Madurai | 625020 | 2004-03-31 | male | BE | - | single | - | 9952816412 | Baskaran K | Father | True | - | False | False | 117 |

**Summary:** Total Phone: 18028135993, Total Emergency Contact: 19741600310
```

### Q: Did he work a full 8-hour day?
- **Status**: ❌ FAILED
- **Time**: 9.39s
- **Database Rows Processed**: 100
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
Based on the provided database result, there is no record of an employee working a full 8-hour day. The "attendance_worked_hour" column shows various hours worked, but none of them exactly match 8 hours. The closest values are "09:23", "09:28", "09:32", "09:35", "09:36", "09:38", "09:39", "09:41", and "09:58", which are all close to but not exactly 8 hours. Therefore, the answer to the user's question is that there is no record of the employee working a full 8-hour day.
```

### Q: Did he work overtime that day?
- **Status**: ✅ PASSED
- **Time**: 2.74s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total is 34500.
```

### Q: How many hours did Ebenezar work this week?
- **Status**: ✅ PASSED
- **Time**: 3.35s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Ebenezar worked 12.25 hours this week.
```

### Q: What was his average working time this month?
- **Status**: ✅ PASSED
- **Time**: 1.77s
- **Database Rows Processed**: 100
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
| Id | Created At | Is Active | Attendance Date | Attendance Clock In Date | Attendance Clock In | Attendance Clock Out Date | Attendance Clock Out | Attendance Worked Hour | Minimum Hour | Attendance Overtime | Attendance Overtime Approve | Attendance Validated | At Work Second | Overtime Second | Approved Overtime Second | Is Validate Request | Is Bulk Request | Is Validate Request Approved | Request Description | Request Type | Is Holiday | Requested Data | Attendance Day Id | Batch Attendance Id Id | Created By Id | Employee Id Id | Modified By Id | Shift Id Id | Work Type Id Id | Modified Time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 16636 | 2026-09-01T03:35:26.087146+00:00 | True | 2026-09-01 | 2026-09-01 | 08:50:49 | - | - | 00:00 | 08:10 | 00:00 | False | False | 0 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 68 | - | 2 | 2 | - |
| 16639 | 2026-09-01T04:15:25.874652+00:00 | True | 2026-09-01 | 2026-09-01 | 09:29:47 | 2026-09-01 | 18:07:43 | 08:23 | 08:10 | 00:13 | False | True | 30180 | 780 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 58 | - | 2 | 2 | 2026-09-01T12:56:01.875348+00:00 |
| 16642 | 2026-09-01T04:35:26.766348+00:00 | True | 2026-09-01 | 2026-09-01 | 09:48:55 | 2026-09-01 | 18:00:08 | 08:12 | 08:10 | 00:02 | False | True | 29520 | 120 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 114 | - | 2 | 2 | 2026-09-01T12:36:10.485537+00:00 |
| 16656 | 2026-09-01T04:55:30.478451+00:00 | True | 2026-09-01 | 2026-09-01 | 10:13:42 | 2026-09-01 | 19:51:14 | 08:43 | 00:00 | 06:00 | False | True | 31380 | 21600 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 112 | - | - | - | 2026-09-01T14:36:10.618513+00:00 |
| 16665 | 2026-09-01T04:56:06.870946+00:00 | True | 2026-09-01 | 2026-09-01 | 10:26:06.506856 | 2026-09-01 | 18:52:11.319483 | 08:26 | 08:10 | 00:16 | False | True | 30360 | 960 | 0 | False | False | False | - | update_request | False | - | 2 | - | 52 | 52 | 52 | 2 | 2 | 2026-09-01T13:22:11.864594+00:00 |
| 16654 | 2026-09-01T04:55:28.844025+00:00 | True | 2026-09-01 | 2026-09-01 | 10:12:20 | 2026-09-01 | 20:08:02 | 09:38 | 08:10 | 01:28 | False | True | 34680 | 5280 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 55 | - | 2 | 2 | 2026-09-01T14:56:07.730321+00:00 |
| 16637 | 2026-09-01T03:55:25.968752+00:00 | True | 2026-09-01 | 2026-09-01 | 09:13:01 | 2026-09-01 | 18:01:03 | 08:26 | 08:10 | 00:16 | False | True | 30360 | 960 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 87 | - | 2 | 2 | 2026-09-01T12:36:13.195846+00:00 |
| 16653 | 2026-09-01T04:55:28.296028+00:00 | True | 2026-09-01 | 2026-09-01 | 10:09:57 | 2026-09-01 | 19:59:19 | 09:34 | 08:10 | 01:24 | False | True | 34440 | 5040 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 116 | - | 2 | 2 | 2026-09-01T14:36:38.022205+00:00 |
| 16655 | 2026-09-01T04:55:29.496014+00:00 | True | 2026-09-01 | 2026-09-01 | 10:12:22 | 2026-09-01 | 20:01:40 | 09:27 | 08:10 | 01:17 | False | True | 34020 | 4620 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 64 | - | 2 | 2 | 2026-09-01T14:36:44.315350+00:00 |
| 16662 | 2026-09-01T04:55:34.944052+00:00 | True | 2026-09-01 | 2026-09-01 | 10:20:48 | 2026-09-01 | 20:01:38 | 06:44 | 08:10 | 00:00 | False | True | 24240 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 101 | - | 2 | 2 | 2026-09-01T14:36:42.224515+00:00 |
| 16644 | 2026-09-01T04:35:27.767219+00:00 | True | 2026-09-01 | 2026-09-01 | 09:52:06 | 2026-09-01 | 19:59:14 | 09:45 | 00:00 | 06:00 | False | True | 35100 | 21600 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 94 | - | 1 | 2 | 2026-09-01T14:36:35.794856+00:00 |
| 16651 | 2026-09-01T04:55:27.277905+00:00 | True | 2026-09-01 | 2026-09-01 | 10:06:06 | 2026-09-01 | 19:57:22 | 09:31 | 08:10 | 01:21 | False | True | 34260 | 4860 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 104 | - | 2 | 2 | 2026-09-01T14:36:23.294207+00:00 |
| 16666 | 2026-09-01T05:15:26.320883+00:00 | True | 2026-09-01 | 2026-09-01 | 10:25:08 | 2026-09-01 | 19:31:14 | 08:11 | 08:10 | 00:01 | False | True | 29460 | 60 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 95 | - | 2 | 2 | 2026-09-01T14:16:13.646659+00:00 |
| 16641 | 2026-09-01T04:35:26.260791+00:00 | True | 2026-09-01 | 2026-09-01 | 09:45:17 | 2026-09-01 | 19:58:23 | 09:58 | 08:10 | 01:48 | False | True | 35880 | 6480 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 39 | - | 2 | 2 | 2026-09-01T14:36:33.705330+00:00 |
| 16658 | 2026-09-01T04:55:32.598474+00:00 | True | 2026-09-01 | 2026-09-01 | 10:16:51 | 2026-09-01 | 19:52:11 | 08:23 | 08:10 | 00:13 | False | True | 30180 | 780 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 79 | - | 2 | 2 | 2026-09-01T14:36:17.030756+00:00 |
| 16664 | 2026-09-01T04:55:35.929307+00:00 | True | 2026-09-01 | 2026-09-01 | 10:22:36 | 2026-09-01 | 19:58:03 | 08:28 | 08:10 | 00:18 | False | True | 30480 | 1080 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 98 | - | 2 | 2 | 2026-09-01T14:36:29.537962+00:00 |
| 16649 | 2026-09-01T04:55:26.184370+00:00 | True | 2026-09-01 | 2026-09-01 | 10:06:02 | 2026-09-01 | 20:46:06 | 10:13 | 08:10 | 02:03 | False | True | 36780 | 7380 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 44 | 88 | 2 | 2 | 2026-09-03T04:14:29.502492+00:00 |
| 16663 | 2026-09-01T04:55:35.431849+00:00 | True | 2026-09-01 | 2026-09-01 | 10:22:32 | 2026-09-01 | 19:25:05 | 08:31 | 08:10 | 00:21 | False | True | 30660 | 1260 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 41 | - | 2 | 2 | 2026-09-01T13:57:26.479566+00:00 |
| 16660 | 2026-09-01T04:55:33.963501+00:00 | True | 2026-09-01 | 2026-09-01 | 10:17:37 | 2026-09-01 | 19:57:24 | 08:44 | 08:10 | 00:34 | False | True | 31440 | 2040 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 38 | - | 2 | 2 | 2026-09-01T14:36:25.367341+00:00 |
| 16643 | 2026-09-01T04:35:27.265597+00:00 | True | 2026-09-01 | 2026-09-01 | 09:51:15 | 2026-09-01 | 19:50:17 | 09:41 | 08:10 | 01:31 | False | True | 34860 | 5460 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 103 | - | 2 | 2 | 2026-09-01T14:36:06.724318+00:00 |
| 16661 | 2026-09-01T04:55:34.454800+00:00 | True | 2026-09-01 | 2026-09-01 | 10:18:55 | 2026-09-01 | 19:53:00 | 08:36 | 08:10 | 00:26 | False | True | 30960 | 1560 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 105 | - | 2 | 2 | 2026-09-01T14:36:19.117508+00:00 |
| 16650 | 2026-09-01T04:55:26.692321+00:00 | True | 2026-09-01 | 2026-09-01 | 10:06:05 | 2026-09-01 | 19:26:45 | 08:34 | 08:10 | 00:24 | False | True | 30840 | 1440 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 80 | - | 2 | 2 | 2026-09-01T14:16:09.351201+00:00 |
| 16646 | 2026-09-01T04:35:28.777879+00:00 | True | 2026-09-01 | 2026-09-01 | 09:56:59 | 2026-09-01 | 19:29:42 | 08:38 | 08:10 | 00:28 | False | True | 31080 | 1680 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 110 | - | 2 | 2 | 2026-09-01T14:16:11.527354+00:00 |
| 16648 | 2026-09-01T04:35:30.776488+00:00 | True | 2026-09-01 | 2026-09-01 | 10:04:16 | 2026-09-01 | 19:51:45 | 08:44 | 08:10 | 00:34 | False | True | 31440 | 2040 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 106 | - | 2 | 2 | 2026-09-01T14:36:14.790949+00:00 |
| 16673 | 2026-09-01T05:15:34.520631+00:00 | True | 2026-09-01 | 2026-09-01 | 10:35:55 | 2026-09-01 | 19:58:05 | 08:08 | 08:10 | 00:00 | False | True | 29280 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 63 | - | 2 | 2 | 2026-09-01T14:36:31.616211+00:00 |
| 16669 | 2026-09-01T05:15:28.884438+00:00 | True | 2026-09-01 | 2026-09-01 | 10:28:45 | 2026-09-01 | 20:01:34 | 09:05 | 08:10 | 00:55 | False | True | 32700 | 3300 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 102 | - | 2 | 2 | 2026-09-01T14:36:40.113949+00:00 |
| 16675 | 2026-09-01T05:35:26.020860+00:00 | True | 2026-09-01 | 2026-09-01 | 10:58:36 | 2026-09-01 | 20:46:27 | 09:01 | 08:10 | 00:51 | False | True | 32460 | 3060 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 1 | - | 2 | 2 | 2026-09-01T15:35:58.405344+00:00 |
| 16674 | 2026-09-01T05:15:35.995381+00:00 | True | 2026-09-01 | 2026-09-01 | 10:36:04 | 2026-09-01 | 20:46:31 | 08:50 | 08:10 | 00:40 | False | True | 31800 | 2400 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 35 | - | 2 | 2 | 2026-09-01T15:36:00.001325+00:00 |
| 16677 | 2026-09-02T03:17:29.517736+00:00 | True | 2026-09-02 | 2026-09-02 | 08:37:17 | - | - | 00:00 | 08:10 | 00:00 | False | False | 0 | 0 | 0 | False | False | False | - | update_request | False | - | 3 | - | - | 68 | - | 2 | 2 | - |
| 16668 | 2026-09-01T05:15:27.705634+00:00 | True | 2026-09-01 | 2026-09-01 | 10:28:42 | 2026-09-01 | 18:05:37 | 07:09 | 08:10 | 00:00 | False | True | 25740 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 67 | - | 2 | 2 | 2026-09-01T12:37:24.373006+00:00 |
| 16638 | 2026-09-01T04:12:23.144643+00:00 | True | 2026-09-01 | 2026-09-01 | 09:42:22.764429 | 2026-09-01 | 18:38:48.534377 | 08:03 | 08:10 | 00:00 | False | True | 28980 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | 114 | 113 | 114 | 2 | 2 | 2026-09-01T13:08:49.724403+00:00 |
| 16645 | 2026-09-01T04:35:28.273510+00:00 | True | 2026-09-01 | 2026-09-01 | 09:53:14 | 2026-09-01 | 19:16:21 | 07:30 | 00:00 | 06:00 | False | True | 27000 | 21600 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 117 | - | - | - | 2026-09-01T13:56:09.759359+00:00 |
| 16670 | 2026-09-01T05:15:30.248300+00:00 | True | 2026-09-01 | 2026-09-01 | 10:29:42 | 2026-09-01 | 19:20:49 | 08:17 | 08:10 | 00:07 | False | True | 29820 | 420 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 78 | - | 2 | 2 | 2026-09-01T13:56:12.955728+00:00 |
| 16667 | 2026-09-01T05:15:26.832729+00:00 | True | 2026-09-01 | 2026-09-01 | 10:27:52 | 2026-09-01 | 19:23:29 | 08:25 | 08:10 | 00:15 | False | True | 30300 | 900 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 56 | - | 2 | 2 | 2026-09-01T13:56:17.806482+00:00 |
| 16671 | 2026-09-01T05:15:31.777771+00:00 | True | 2026-09-01 | 2026-09-01 | 10:31:44 | 2026-09-01 | 19:26:24 | 08:43 | 08:10 | 00:33 | False | True | 31380 | 1980 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 88 | - | 2 | 2 | 2026-09-01T14:16:06.656995+00:00 |
| 16647 | 2026-09-01T04:35:29.731603+00:00 | True | 2026-09-01 | 2026-09-01 | 09:59:39 | 2026-09-01 | 19:32:20 | 08:48 | 08:10 | 00:38 | False | True | 31680 | 2280 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 107 | - | 2 | 2 | 2026-09-01T14:16:15.808316+00:00 |
| 16652 | 2026-09-01T04:55:27.791965+00:00 | True | 2026-09-01 | 2026-09-01 | 10:09:50 | 2026-09-01 | 19:38:15 | 08:39 | 08:10 | 00:29 | False | True | 31140 | 1740 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 115 | - | 2 | 2 | 2026-09-01T14:16:18.069531+00:00 |
| 16659 | 2026-09-01T04:55:33.472190+00:00 | True | 2026-09-01 | 2026-09-01 | 10:16:54 | 2026-09-01 | 19:50:58 | 08:08 | 08:10 | 00:00 | False | True | 29280 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 60 | - | 2 | 2 | 2026-09-01T14:36:08.542507+00:00 |
| 16657 | 2026-09-01T04:55:31.607481+00:00 | True | 2026-09-01 | 2026-09-01 | 10:16:50 | 2026-09-01 | 19:51:42 | 09:02 | 08:10 | 00:52 | False | True | 32520 | 3120 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 59 | - | 2 | 2 | 2026-09-01T14:36:12.691987+00:00 |
| 16676 | 2026-09-01T09:37:58.939182+00:00 | True | 2026-09-01 | 2026-09-01 | 14:26:23 | 2026-09-01 | 19:55:40 | 05:29 | 08:10 | 00:00 | False | True | 19740 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 36 | - | 2 | 2 | 2026-09-01T14:36:21.201524+00:00 |
| 16672 | 2026-09-01T05:15:33.161490+00:00 | True | 2026-09-01 | 2026-09-01 | 10:31:47 | 2026-09-01 | 17:38:21 | 06:47 | 08:10 | 00:00 | False | True | 24420 | 0 | 0 | False | False | False | - | update_request | False | - | 2 | - | - | 83 | - | 2 | 2 | 2026-09-01T14:36:27.413509+00:00 |
| 16703 | 2026-09-02T04:57:38.860747+00:00 | True | 2026-09-02 | 2026-09-02 | 10:25:07 | 2026-09-02 | 19:29:52 | 08:46 | 08:10 | 00:36 | False | True | 31560 | 2160 | 0 | False | False | False | - | update_request | False | - | 3 | - | - | 82 | - | 2 | 2 | 2026-09-02T14:16:11.655526+00:00 |
| 16687 | 2026-09-02T04:57:30.777332+00:00 | True | 2026-09-02 | 2026-09-02 | 10:11:33 | 2026-09-02 | 19:49:25 | 09:12 | 08:10 | 01:02 | False | True | 33120 | 3720 | 0 | False | False | False | - | update_request | False | - | 3 | - | - | 106 | - | 2 | 2 | 2026-09-02T14:36:07.023348+00:00 |
| 16690 | 2026-09-02T04:57:32.253625+00:00 | True | 2026-09-02 | 2026-09-02 | 10:13:17 | 2026-09-02 | 19:41:38 | 08:34 | 08:10 | 00:24 | False | True | 30840 | 1440 | 0 | False | False | False | - | update_request | False | - | 3 | - | - | 115 | - | 2 | 2 | 2026-09-02T14:16:32.799933+00:00 |
| 16682 | 2026-09-02T04:37:30.624261+00:00 | True | 2026-09-02 | 2026-09-02 | 09:55:18 | 2026-09-02 | 19:40:13 | 08:48 | 08:10 | 00:38 | False | True | 31680 | 2280 | 0 | False | False | False | - | update_request | False | - | 3 | - | - | 46 | - | 2 | 2 | 2026-09-02T14:16:28.630942+00:00 |
| 16679 | 2026-09-02T04:17:29.677875+00:00 | True | 2026-09-02 | 2026-09-02 | 09:43:54 | 2026-09-02 | 19:35:44 | 07:15 | 00:00 | 06:00 | False | True | 26100 | 21600 | 0 | False | False | False | - | update_request | False | - | 3 | - | - | 117 | - | - | - | 2026-09-02T14:16:15.923325+00:00 |
| 16681 | 2026-09-02T04:37:30.124772+00:00 | True | 2026-09-02 | 2026-09-02 | 09:53:16 | 2026-09-02 | 19:43:21 | 09:32 | 08:10 | 01:22 | False | True | 34320 | 4920 | 0 | False | False | False | - | update_request | False | - | 3 | - | - | 103 | - | 2 | 2 | 2026-09-02T14:16:37.119931+00:00 |
| 16704 | 2026-09-02T04:57:39.346660+00:00 | True | 2026-09-02 | 2026-09-02 | 10:26:21 | 2026-09-02 | 19:53:41 | 08:32 | 08:10 | 00:22 | False | True | 30720 | 1320 | 0 | False | False | False | - | update_request | False | - | 3 | - | - | 39 | - | 2 | 2 | 2026-09-02T14:36:26.992340+00:00 |
| 16684 | 2026-09-02T04:37:31.610162+00:00 | True | 2026-09-02 | 2026-09-02 | 10:00:09 | 2026-09-02 | 20:10:25 | 09:53 | 08:10 | 01:43 | False | True | 35580 | 6180 | 0 | False | False | False | - | update_request | False | - | 3 | - | - | 44 | - | 2 | 2 | 2026-09-02T14:56:09.597101+00:00 |
| 16697 | 2026-09-02T04:57:35.676609+00:00 | True | 2026-09-02 | 2026-09-02 | 10:18:23 | 2026-09-02 | 19:44:27 | 08:25 | 08:10 | 00:15 | False | True | 30300 | 900 | 0 | False | False | False | - | update_request | False | - | 3 | - | - | 95 | - | 2 | 2 | 2026-09-02T14:17:25.386137+00:00 |

*Showing first 50 of 100 records.*

**Summary:** Total At Work Second: 2996400, Total Overtime Second: 338220, Total Approved Overtime Second: 0
```

### Q: Which day did he spend the most time at work?
- **Status**: ✅ PASSED
- **Time**: 22.88s
- **Database Rows Processed**: 100
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The day he spent the most time at work is not specified in the database result, as the data only contains information about an employee named Sheeladevi, not a male employee. However, based on the data provided for Sheeladevi, the day she spent the most time at work was on "2025-07-19" with a total of 183300 seconds (or 50 hours and 55 minutes) of work, and on "2025-08-14" with a total of 64320 seconds (or 17 hours and 52 minutes) of work, and also on "2025-07-03" with a total of 33780 seconds (or 9 hours and 23 minutes) of work, including overtime.
```

## Level 3 - Joins and Relationships

### Q: How many times did Ebenezar S clock in and out on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 3.50s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total count is 0.
```

### Q: List all clock-in and clock-out activities for Ebenezar S on 2026-09-01.
- **Status**: ✅ PASSED
- **Time**: 1.70s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Clock Out**: 19:58:23
- **Attendance Date**: 2026-09-01
- **Attendance Clock In**: 09:45:17
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Is Active**: True
- **Gender**: male
```

### Q: What was Ebenezar S's first clock-in time on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 1.49s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Date**: 2026-09-01
- **Attendance Clock In**: 09:45:17
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Gender**: male
- **Attendance Overtime**: 01:48
```

### Q: What was Ebenezar S's last clock-out time on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 1.65s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Clock Out**: 19:58:23
- **Attendance Date**: 2026-09-01
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Attendance Overtime**: 01:48
```

### Q: Calculate the total time between all clock-in and clock-out periods for Ebenezar S on 2026-09-01.
- **Status**: ❌ FAILED
- **Time**: 2.98s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: Did Ebenezar S have multiple attendance sessions on 2026-09-01?
- **Status**: ❌ FAILED
- **Time**: 1.38s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: How much total time did Ebenezar S spend at work across all attendance activities on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 2.11s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total count is 1.
```

### Q: How long was Ebenezar S outside the workplace between clock-out and the next clock-in?
- **Status**: ✅ PASSED
- **Time**: 2.34s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Worked Hour**: 03:33
- **Attendance Clock Out**: 13:27:30
- **Attendance Date**: 2026-09-16
- **Attendance Clock In**: 09:54:49
- **At Work Second**: 12780
- **Badge Id**: 9
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Gender**: male
```

### Q: What was the longest attendance session of Ebenezar S on 2026-09-01?
- **Status**: ✅ PASSED
- **Time**: 0.94s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Attendance Clock Out**: 19:58:23
- **Attendance Date**: 2026-09-01
- **Attendance Clock In**: 09:45:17
- **Employee Last Name**: S
- **Employee First Name**: Ebenezar
- **Gender**: male
```

### Q: What was the shortest attendance session of Ebenezar S on 2026-09-01?
- **Status**: ❌ FAILED
- **Time**: 1.01s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

### Q: How many hours did Ebenezar S work each day during September 2026?
- **Status**: ❌ FAILED
- **Time**: 5.81s
- **Database Rows Processed**: 1
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
Based on the database result, there is 1 record found for Ebenezar S. The total worked hours recorded is 82.3666666666666667 hours. However, the database result does not provide a breakdown of hours worked per day. Therefore, it is not possible to determine the number of hours Ebenezar S worked each day during September 2026 based on the provided data.
```

### Q: What was Ebenezar S's total working time during September 2026?
- **Status**: ✅ PASSED
- **Time**: 1.00s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total count is 10.
```

### Q: What was Ebenezar S's average working time per day during September 2026?
- **Status**: ✅ PASSED
- **Time**: 1.43s
- **Database Rows Processed**: 10
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
| Is Holiday | Attendance Date | Employee First Name |
| --- | --- | --- |
| False | 2026-09-01 | Ebenezar |
| False | 2026-09-02 | Ebenezar |
| False | 2026-09-03 | Ebenezar |
| False | 2026-09-07 | Ebenezar |
| False | 2026-09-08 | Ebenezar |
| False | 2026-09-09 | Ebenezar |
| False | 2026-09-10 | Ebenezar |
| False | 2026-09-11 | Ebenezar |
| False | 2026-09-15 | Ebenezar |
| False | 2026-09-16 | Ebenezar |
```

### Q: On which day did Ebenezar S work the most hours?
- **Status**: ✅ PASSED
- **Time**: 20.16s
- **Database Rows Processed**: 100
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
To answer the question "On which day did Ebenezar S work the most hours?", we need to examine the "attendance_worked_hour" field for each record where the employee's first name is "Ebenezar" and last name is "S".

Upon reviewing the data, the maximum "attendance_worked_hour" is "50:01" which is found in the record with id "1008". This record corresponds to the attendance date "2025-07-19". 

Therefore, Ebenezar S worked the most hours on 2025-07-19.
```

### Q: On which day did Ebenezar S work the least hours?
- **Status**: ✅ PASSED
- **Time**: 1.29s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Matching record details:
- **Id**: 431
- **Badge Id**: 9
- **Employee First Name**: Ebenezar
- **Employee Last Name**: S
- **Employee Profile**: 
- **Email**: ebenezars@gramosoft.in
- **Phone**: +918838913541
- **Address**: 183, Sandapettai Street, Srivilliputhur - 626125.
- **Country**: India
- **State**: Tamil Nadu
- **City**: Srivilliputhur
- **Zip**: 626125.
- **Dob**: 1999-07-29
- **Gender**: male
- **Qualification**: Bsc IT
- **Experience**: N/A
- **Marital Status**: single
- **Children**: N/A
- **Emergency Contact**: 7387672230
- **Emergency Contact Name**: Rachel
- **Emergency Contact Relation**: Sister
- **Is Active**: True
- **Additional Info**: N/A
- **Is From Onboarding**: False
- **Is Directly Converted**: False
- **Employee User Id Id**: 39
- **Created At**: 2025-06-30T15:02:15.749927+00:00
- **Attendance Date**: 2025-06-30
- **Attendance Clock In Date**: 2025-06-30
- **Attendance Clock In**: 19:38:00
- **Attendance Clock Out Date**: 2025-06-30
- **Attendance Clock Out**: 19:38:00
- **Attendance Worked Hour**: 00:00
- **Minimum Hour**: 08:10
- **Attendance Overtime**: 00:00
- **Attendance Overtime Approve**: False
- **Attendance Validated**: True
- **At Work Second**: 0
- **Overtime Second**: 0
- **Approved Overtime Second**: 0
- **Is Validate Request**: False
- **Is Bulk Request**: False
- **Is Validate Request Approved**: False
- **Request Description**: N/A
- **Request Type**: update_request
- **Is Holiday**: False
- **Requested Data**: N/A
- **Attendance Day Id**: 1
- **Batch Attendance Id Id**: N/A
- **Created By Id**: N/A
- **Employee Id Id**: 39
- **Modified By Id**: N/A
- **Shift Id Id**: 2
- **Work Type Id Id**: 2
- **Modified Time**: N/A
```

### Q: How many days did Ebenezar S work more than 8 hours during September 2026?
- **Status**: ❌ FAILED
- **Time**: 7.26s
- **Database Rows Processed**: 1
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
Based on the database result, there is 1 record for Ebenezar S. However, the provided data only includes the total worked hours ("70.8333333333333333") for the period, but does not specify the individual days or hours worked per day. Therefore, it is not possible to determine the exact number of days Ebenezar S worked more than 8 hours during September 2026 based on the given data.
```

### Q: How many days did Ebenezar S work less than 8 hours?
- **Status**: ✅ PASSED
- **Time**: 3.38s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
Based on the database result, there is 1 record of Ebenezar S working less than 8 hours, with the worked hours being exactly 4.2166666666666667 hours.
```

### Q: How many days was Ebenezar S absent during September 2026?
- **Status**: ❌ FAILED
- **Time**: 4.92s
- **Database Rows Processed**: 1
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
The total count is None.
```

### Q: How many attendance records does Ebenezar S have during September 2026?
- **Status**: ✅ PASSED
- **Time**: 1.34s
- **Database Rows Processed**: 1
- **Reasoning**: Answer provided and successfully parsed.
- **Answer**:
```text
The total count is 0.
```

### Q: Show the daily worked hours for Ebenezar S from 2026-09-01 to 2026-09-15.
- **Status**: ❌ FAILED
- **Time**: 1.39s
- **Database Rows Processed**: 0
- **Reasoning**: System failed to find the answer or provided an empty response.
- **Answer**:
```text
No matching records were found in the database for this query.
```

## 📊 Overall Analytics

| Metric | Value |
| --- | --- |
| Total Questions | 85 |
| Passed | 58 |
| Failed | 27 |
| Success Rate | 68.2% |
| Total Execution Time | 411.40s |
| Avg Time / Question | 4.84s |

### Breakdown by Level

| Level | Total | Passed | Failed | Success % | Avg Time (s) |
| --- | --- | --- | --- | --- | --- |
| Level 1 - Basic Select and Filters | 10 | 9 | 1 | 90.0% | 3.77s |
| Level 2 - Aggregations and Grouping | 55 | 36 | 19 | 65.5% | 5.58s |
| Level 3 - Joins and Relationships | 20 | 13 | 7 | 65.0% | 3.35s |
