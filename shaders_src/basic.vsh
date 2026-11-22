//
//  basic.vsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.
//

#ifndef ENABLE_SHADER_FEATURES

// Enable high-quality fog
#ifndef SUN_FOG
#define SUN_FOG
#endif

#endif//ENABLE_SHADER_FEATURES

// This is for normal rendering
//%0define QUALITY_LEVEL 0

// This is for when rendering to the cube maps
//%1define QUALITY_LEVEL 1
//%1undef SPEC_MAP
//%1undef PER_PIXEL_SPEC
//%1undef FOG
//%1undef DETAIL_MAP

// Night time rendering, but not to the cube maps
//%2define QUALITY_LEVEL 0
//%2define NIGHT

//%include utility.xsh
//%include basicv.xsh
