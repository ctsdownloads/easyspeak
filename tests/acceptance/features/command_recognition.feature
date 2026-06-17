Feature: Friendly feedback when a command isn't understood
  As someone controlling my Linux desktop by voice
  I want unrecognised speech handled gently and only nudged toward help once
  So that I'm guided without being nagged or talked over by my own assistant

  (**Note:** These drive route_command directly with stub plugins; the spoken
  replies are read back off the stubbed speech pipeline.)

  Background:
    Given a fresh EasySpeak that understands only "help" and "open files"

  Scenario: The first unrecognised command gets a soft apology
    When I say "flibbertigibbet"
    Then EasySpeak's last reply is "Sorry, I didn't understand."
    And the command list is not shown

  Scenario: A second miss shows help once and keeps the mic open
    When I say "flibbertigibbet"
    And I say "wibble wobble"
    Then EasySpeak says "I didn't understand."
    And the command list is shown
    And EasySpeak keeps listening for another command

  Scenario: Repeated misses stop re-showing the command list
    When I say "flibbertigibbet"
    And I say "wibble wobble"
    And I say "more nonsense"
    Then the command list is shown exactly once
    And EasySpeak's last reply is "I didn't understand."

  Scenario: A successful command (including "help") resets the gentle flow
    When I say "flibbertigibbet"
    And I say "wibble wobble"
    And I say "help"
    And I say "more nonsense"
    Then EasySpeak's last reply is "Sorry, I didn't understand."

  # Regression: speak() is non-blocking, so the soft apology is still playing
  # when the loop resumes. An immediate flush only clears the buffer up to that
  # instant, so without draining first the open mic transcribes the assistant's
  # own "Sorry, I didn't understand." and escalates to help with no one speaking.
  Scenario: The soft apology finishes before the mic listens again
    When the wake word fires and EasySpeak hears one unrecognised command
    Then EasySpeak drains its speech before listening again
    And the command list is not shown

  Scenario: A self-heard echo within the grace window can't open help
    When I say "flibbertigibbet"
    And the mic mishears "sorry i didn't understand" a moment later
    Then EasySpeak said "Sorry, I didn't understand." only once
    And the command list is not shown
