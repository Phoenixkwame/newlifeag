# Homepage artwork and design references

## Official church logos

`church-logos.png` is the original transparent 1311 × 586 PNG supplied by the user, copied from `Downloads/Logo (1).png` on September 29, 2026. The file is unchanged. The header uses CSS `object-fit` and right alignment to show the Newlife emblem; the footer shows the complete Assemblies of God / Newlife artwork. Both use white backgrounds for contrast.

## Church Facebook image

`newlife-facebook.jpg` (720 × 720, approximately 66 KB) is the public page image retrieved from https://www.facebook.com/newlyfag/ on September 28, 2026, at the user's request. The page identifies itself as Newlife AG, Tema New Town. The image contains World Assemblies of God Congress Ghana artwork and is displayed uncropped in the homepage's church-family section. No identities or church roles are inferred for the pictured people.

The file is stored locally, rather than referencing Facebook's expiring CDN URL. It also serves as the homepage hero background, replacing the generated artwork at the user's request. CSS places it toward the right on desktop with a dark overlay behind the heading, and across the hero on mobile. Facebook's public response exposed only this image; other gallery images were not available in that response. The section links to the church's page and photo gallery for more photos.

## Original decorative hero

`worship-hero.png` is original illustrative artwork generated with the built-in ImageGen tool. It is not a photograph of Newlife AG. It is retained as an unused asset; the homepage now uses `newlife-facebook.jpg` instead.

Final generation prompt:

> Use case: stylized-concept. Asset type: wide 16:9 church website hero background, 2048x1152. Create an original cinematic, artistic worship scene, viewed from the very back of a contemporary church: softly silhouetted congregation in bottom quarter, a few raised arms, distant subtle cross in warm golden stage light on the right half, beams of amber light in atmospheric haze. Deep forest green and charcoal shadows, rich natural film grain, warm ivory highlights. Painterly photographic realism, people anonymous and out of focus. Left half mostly dark negative space for large cream HTML headline; right half carries luminous composition. Welcoming, hopeful, beautiful and sophisticated. No text, no typography, no logos, no watermarks, no identifiable location or identifiable people. This is illustrative artwork, not a photograph of a real church.

Design research: Elevation Church (https://www.elevationchurch.org/) and Church of the Highlands (https://www.churchofthehighlands.com/), reviewed September 28, 2026. Inspired by their prominent welcome, watch/visit pathways, and community discovery sections. No source code or imagery was copied from those sites.

The CSS and JavaScript live here so Django's staticfiles discovery and production collectstatic process include them. Run `python manage.py collectstatic` during deployment. Homepage text uses Django translation tags; new strings need reviewed Twi translations in the existing locale catalog.

## Full-screen slideshow (October 2026)
User-supplied assets copied unchanged from Downloads:
- church-worship.jpg: IMG_1018.jpg.jpeg
- church-congregation.jpg: IMG_1257.jpg.jpeg
- core-values.png: ChatGPT Image Aug 28, 2026, 11_11_14 PM.png (matches attached core-values artwork)
Replace these files to change the permanent slides. Additional active homepage flyers are included automatically. Template: templates/includes/home_slideshow.html. Rotation: 8 seconds, pauses on hover/focus and respects reduced-motion preferences. No reference-church artwork is used.
