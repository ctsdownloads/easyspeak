Feature: Volume control by voice
  As someone controlling my Linux desktop by voice
  I want volume commands to react every time and to have instant extremes
  So that I can nudge the volume repeatedly or jump to loud/silent at once

  Background:
    Given a fresh EasySpeak with the system plugin

  Scenario: Saying "louder" repeatedly raises the volume each time
    When I say "louder"
    And I say "louder"
    And I say "louder"
    Then the volume was raised 3 times

  Scenario: Saying "more silent" repeatedly lowers the volume each time
    When I say "more silent"
    And I say "more silent"
    Then the volume was lowered 2 times

  Scenario: "very loud" jumps to maximum volume instantly
    When I say "very loud"
    Then the volume is set to maximum

  Scenario: "very silent" drops to minimum volume instantly
    When I say "very silent"
    Then the volume is set to minimum
