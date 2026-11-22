//
//  black_and_white.vsh
//
//  Created by bend on 06/09/13.
//  Copyright EA 2013. All rights reserved.
//

// Use EXT_shader_framebuffer_fetch extension if available
//
//   Defines FRAMEBUFFER_RGBA as the source fragment colour
//

#ifdef FRAMEBUFFER_FETCH
	#extension GL_EXT_shader_framebuffer_fetch : require
	#define FRAMEBUFFER_RGBA gl_LastFragData[0]
#else
	uniform lowp sampler2D s_Texture0;		// Screen texture
	varying lowp vec2 v_TexCoord;
	#define FRAMEBUFFER_RGBA texture2D(s_Texture0, v_TexCoord)
#endif

void main()
{
	lowp vec3 colour = FRAMEBUFFER_RGBA.rgb;
	
	highp float grey = (0.3 * colour.r)
					 + (0.6 * colour.g)
					 + (0.1 * colour.b);
	gl_FragColor = vec4( grey, grey, grey, 1.0 );
}

