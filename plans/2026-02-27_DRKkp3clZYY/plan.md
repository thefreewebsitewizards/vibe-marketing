# No-Show Recovery System with Frame Control

**Source:** [Nick Njuguna | High Ticket Sales Coach](https://www.instagram.com/reel/DRKkp3clZYY/?igsh=YWhibDNxaGYwdG1i)
**Category:** sales
**Relevance:** 90%
**Total Hours:** 12.0h
**Status:** review

## Summary

Implement professional no-show handling sequences that maintain our premium positioning and increase callback rates. Uses 'running late' excuse and priority-based language to flip the script on prospects.

## Key Insights

- We could adapt the 'running late' excuse for our appointment setting - when prospects no-show, have our AI chatbot or team member say our previous consultation ran over due to complex setup needs
- Apply the frame control technique by never saying 'if you have time' - instead use 'if this is still a priority' to maintain our value position when rescheduling discovery calls
- We could implement a two-step no-show sequence: immediate 'running late' outreach, then 5-minute delayed 'put it in their court' message through our automated follow-up system
- Use the psychological positioning of making prospects prove the meeting is important to them rather than us chasing - builds scarcity around our consultation spots
- We could train our appointment setters to never sound desperate when prospects miss calls - desperation kills callback rates and undermines our premium positioning
- Apply the 'I'll open up my calendar and see if I can make it work' language to make our availability seem exclusive and valuable rather than always available

## Swipe Phrases

- My last call went 10 minutes over - we were talking for a while and there was so much going on with onboarding [outreach]
- I completely blanked on our call [outreach]
- If this is still a priority, let me know and I can find some time in my schedule [email/outreach]
- Only if it's important to you, so let me know [email/outreach]
- I'll open up my calendar and see if I can make it work [outreach]
- Their time was ultimately worth less than mine [internal mindset]
- You're subconsciously telling them that you don't respect your time [training material]
- So much going on with onboarding [social proof phrase for ads]
- If you have some time we can pop back in [avoid this - noted as weak language]
- Probably some of the best advice that I've heard [testimonial format for social posts]

## Tasks

### 1. Build No-Show Recovery Automation in GHL
**Priority:** high | **Hours:** 2.0h | **Tools:** ghl

Create two-part SMS/email sequence triggered when prospect misses discovery call. Sequence 1 (immediate): 'Hey [Name], my last consultation went 10 minutes over - we were talking for a while and there was so much going on with onboarding. I completely blanked on our call. My fault!' Sequence 2 (5 minutes later): 'If this is still a priority, let me know and I can find some time in my schedule. Only if it's important to you though - I'll open up my calendar and see if I can make it work.'

**Deliverables:**
- GHL workflow with 2-step no-show sequence using exact swipe phrases
- Email templates: Sequence 1 subject line 'My fault - consultation overran', Sequence 2 subject line 'If this is still important to you'
- SMS templates with character count optimization

### 2. Update Appointment Setter Scripts
**Priority:** high | **Hours:** 1.5h | **Tools:** ghl

Replace all weak language in rescheduling scripts. Remove 'if you have time' → 'if this is still a priority'. Remove 'whenever you're available' → 'I'll open up my calendar and see if I can make it work'. Add 'there was so much going on with onboarding' as social proof when explaining delays. Train on mindset: their time was ultimately worth less than ours if they no-showed.

**Deliverables:**
- Updated phone script document with frame control language
- Training checklist: 'You're subconsciously telling them that you don't respect your time' reminder
- Role-play scenarios using new positioning language

### 3. Create No-Show Training Module for Team
**Priority:** high | **Hours:** 2.5h | **Tools:** claude_code

Build training content teaching frame control principles. Module covers: never sound desperate (kills callback rates), always maintain premium positioning, use 'running late due to complex client needs' positioning. Include the swipe phrase 'Probably some of the best advice that I've heard' as format for collecting testimonials about our consultation process.

**Deliverables:**
- Training video script covering desperation vs. frame control
- Quick reference card with approved vs. banned phrases
- Testimonial collection template using 'best advice' format

### 4. Configure n8n Trigger for No-Show Detection
**Priority:** medium | **Hours:** 1.5h | **Tools:** n8n, ghl

Build workflow that monitors GHL calendar for missed appointments, automatically tags prospect as 'no-show', and triggers the recovery sequence. Include logic to track response rates and identify which prospects respond to priority-based language vs. those who don't (for lead scoring).

**Deliverables:**
- n8n workflow connecting GHL calendar to automation triggers
- Tagging system for no-show behavior tracking
- Response rate tracking dashboard

**Depends on:** Build No-Show Recovery Automation in GHL

### 5. Update Website Copy with Scarcity Language
**Priority:** medium | **Hours:** 1.0h | **Tools:** website, claude_code

Replace booking page copy to reflect exclusive positioning. Change 'Book your free consultation' → 'I'll open up my calendar and see if I can make it work for a strategy session'. Add 'so much going on with onboarding' as social proof near booking section. Update consultation descriptions to emphasize complex client needs and setup requirements.

**Deliverables:**
- Updated booking page with scarcity-based CTA text
- Social proof section featuring 'complex onboarding' language
- Consultation value proposition emphasizing exclusivity

### 6. Create Meta Ad Copy Using Social Proof Language
**Priority:** medium | **Hours:** 2.0h | **Tools:** meta_ads, claude_code

Develop ad variations incorporating 'so much going on with onboarding' as social proof element. Test headlines like 'Why Our Onboarding Calls Keep Running Over (Client Results Inside)' and 'The Complex Setup That's Getting Our Clients Results'. Use frame control language in ad copy - avoid 'if you have time' type weak positioning.

**Deliverables:**
- 5 ad headline variations using onboarding social proof
- 3 ad copy versions with frame control positioning
- A/B test setup comparing weak vs. strong language

### 7. Build Telegram Notification System
**Priority:** low | **Hours:** 1.5h | **Tools:** n8n, ghl

Configure Telegram bot to alert team when no-show recovery sequences are triggered and when prospects respond. Include response type classification (immediate reschedule vs. delayed response vs. no response) to help team adjust approach. Send daily summary of no-show recovery rates.

**Deliverables:**
- Telegram bot notifications for no-show events
- Response classification system with alerts
- Daily recovery rate summary reports

**Depends on:** Configure n8n Trigger for No-Show Detection
